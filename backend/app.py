from flask import Flask, jsonify, request
from flask_cors import CORS
import oci
import logging
import time
import re
import os
import secrets
import functools
from datetime import datetime, timezone, timedelta
from dateutil import parser as date_parser
from concurrent.futures import ThreadPoolExecutor, as_completed
from oci_helper import make_client, paginate, get_config_and_signer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
_valid_tokens: set[str] = set()


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not APP_PASSWORD:
            return f(*args, **kwargs)
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        if token not in _valid_tokens:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


@app.route("/api/auth", methods=["POST"])
def auth():
    if not APP_PASSWORD:
        return jsonify({"token": "noauth"})
    data = request.get_json(silent=True) or {}
    if data.get("password") != APP_PASSWORD:
        return jsonify({"error": "Invalid password"}), 401
    token = secrets.token_hex(32)
    _valid_tokens.add(token)
    return jsonify({"token": token})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def serialize(obj):
    """Recursively convert OCI SDK objects / datetimes to JSON-safe types."""
    if obj is None:
        return None
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if hasattr(obj, '__dict__'):
        return {k: serialize(v) for k, v in vars(obj).items() if not k.startswith('_')}
    return obj


def fmt_duration(td: timedelta) -> str:
    if td is None:
        return "Unknown"
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts) if parts else "0s"


def rpo_from_last_sync(last_sync_time) -> dict:
    """Given a last-sync datetime (or ISO string), return RPO info dict."""
    if last_sync_time is None:
        return {"rpo": "Unknown", "last_sync": None}
    if isinstance(last_sync_time, str):
        last_sync_time = date_parser.parse(last_sync_time)
    if last_sync_time.tzinfo is None:
        last_sync_time = last_sync_time.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - last_sync_time
    return {
        "rpo": fmt_duration(delta),
        "last_sync": last_sync_time.isoformat(),
    }


# ---------------------------------------------------------------------------
# Volume Group RPO
# ---------------------------------------------------------------------------

def _region_from_ocid(ocid: str) -> str:
    """
    Extract the region identifier from an OCI OCID.
    Format: ocid1.<type>.<realm>.<region>.<uniqueId>
    The region is always the 4th dot-separated token (index 3).
    """
    try:
        return ocid.split('.', 4)[3]
    except (IndexError, AttributeError):
        return ""


def get_volume_group_rpo_v2(volume_group_id: str, region: str) -> dict:
    """
    VG RPO — cross-region flow:
      1. get_volume_group(primary region)  → vg.volume_group_replicas
         Each entry is a VolumeGroupReplicaInfo with .volume_group_replica_id
      2. The replica OCID encodes its home region (standby region).
         Extract it and create a BlockstorageClient for THAT region.
      3. get_volume_group_replica(replica_id) in the REPLICA's region → .time_last_synced
      Pick the most recent time_last_synced across all replicas.
    """
    try:
        blockstorage_primary = make_client(oci.core.BlockstorageClient, region)
        vg = blockstorage_primary.get_volume_group(volume_group_id).data

        if not vg.volume_group_replicas:
            return {"rpo": "No replica", "last_sync": None}

        best_sync = None
        for vgr_info in vg.volume_group_replicas:
            replica_id = vgr_info.volume_group_replica_id
            if not replica_id:
                continue

            # The replica lives in the standby region — parse it from the OCID
            replica_region = _region_from_ocid(replica_id)
            if not replica_region:
                logger.warning(f"Could not parse region from replica OCID: {replica_id}")
                continue

            try:
                # Query the replica in its own (standby) region
                blockstorage_replica = make_client(oci.core.BlockstorageClient, replica_region)
                replica = blockstorage_replica.get_volume_group_replica(replica_id).data
                t = replica.time_last_synced
                logger.info(f"VG {volume_group_id} replica in {replica_region}: last_synced={t}")
                if t and (best_sync is None or t > best_sync):
                    best_sync = t
            except Exception as e:
                logger.warning(f"VG replica fetch failed for {replica_id} in {replica_region}: {e}")

        return rpo_from_last_sync(best_sync)
    except Exception as e:
        logger.warning(f"VG RPO failed for {volume_group_id}: {e}")
        return {"rpo": "Unknown", "last_sync": None}


# ---------------------------------------------------------------------------
# File System RPO
# ---------------------------------------------------------------------------

def get_filesystem_rpo(filesystem_id: str, region: str) -> dict:
    """
    File System RPO:
      1. get_file_system  → compartment_id + availability_domain
      2. list_replications(compartment_id, availability_domain, file_system_id=...)
         – availability_domain is a required positional param
         – file_system_id is an optional kwarg filter
      3. ReplicationSummary already has recovery_point_time; no second API call needed.
         Pick the most recent recovery_point_time as the RPO.
    """
    try:
        fs_client = make_client(oci.file_storage.FileStorageClient, region)
        fs = fs_client.get_file_system(filesystem_id).data
        compartment_id = fs.compartment_id
        availability_domain = fs.availability_domain

        replications = paginate(
            fs_client.list_replications,
            compartment_id=compartment_id,
            availability_domain=availability_domain,
            file_system_id=filesystem_id,
        )

        if not replications:
            return {"rpo": "No replication", "last_sync": None}

        # ReplicationSummary.recovery_point_time is already present — use it directly
        best_rpt = None
        for rep in replications:
            rpt = getattr(rep, 'recovery_point_time', None)
            if rpt and (best_rpt is None or rpt > best_rpt):
                best_rpt = rpt

        return rpo_from_last_sync(best_rpt)
    except Exception as e:
        logger.warning(f"FS RPO failed for {filesystem_id}: {e}")
        return {"rpo": "Unknown", "last_sync": None}


# ---------------------------------------------------------------------------
# Database RPO (Data Guard apply lag)
# ---------------------------------------------------------------------------

def _get_database_ocid(db_client, member_id: str) -> str:
    """
    The DR member_id for DATABASE type is the Database OCID directly.
    However some configurations store the DB System OCID, so we try both.
    Returns the Database OCID to use with list_data_guard_associations.
    """
    # First: assume it IS already a Database OCID — verify by calling get_database
    try:
        db_client.get_database(member_id)
        return member_id  # it's a Database OCID — use it directly
    except Exception:
        pass

    # Second: treat it as a DB System OCID, list databases inside it
    try:
        db_sys = db_client.get_db_system(member_id).data
        databases = paginate(
            db_client.list_databases,
            compartment_id=db_sys.compartment_id,
            system_id=member_id,   # do NOT pass db_home_id — omitting it skips the filter
        )
        if databases:
            return databases[0].id
    except Exception:
        pass

    return member_id  # last resort: return as-is


def get_database_rpo(database_id: str, region: str) -> dict:
    """
    Database RPO via Data Guard apply_lag — cross-region flow:

      apply_lag is ONLY populated on the STANDBY side of the association.
      Querying from the primary returns apply_lag=None.

      Flow:
        1. Resolve the Database OCID (member_id may be a DB or DB System OCID).
        2. list_data_guard_associations(primary_db_id) — find the AVAILABLE association.
        3. Read peer_database_id from that association; the peer is the standby DB.
        4. Extract the standby region from the peer_database_id OCID.
        5. list_data_guard_associations(peer_database_id) in the STANDBY region
           — the standby association has role=STANDBY and apply_lag populated.
        6. Parse apply_lag into a duration string.
    """
    try:
        db_client = make_client(oci.database.DatabaseClient, region)

        # Step 1 – resolve to Database OCID
        db_ocid = _get_database_ocid(db_client, database_id)
        logger.info(f"DB RPO: resolved member → database OCID {db_ocid}")

        # Step 2 – get DG associations from primary
        primary_assocs = paginate(
            db_client.list_data_guard_associations,
            database_id=db_ocid,
        )
        if not primary_assocs:
            return {"rpo": "No Data Guard", "last_sync": None}

        # Pick the AVAILABLE association (prefer it; fall back to first)
        primary_assoc = next(
            (a for a in primary_assocs if a.lifecycle_state == "AVAILABLE"),
            primary_assocs[0]
        )

        # Step 3 – get peer (standby) database OCID
        peer_db_id = primary_assoc.peer_database_id
        if not peer_db_id:
            return {"rpo": "No peer DB in DG association", "last_sync": None}

        # Step 4 – derive standby region from peer OCID
        standby_region = _region_from_ocid(peer_db_id)
        if not standby_region:
            return {"rpo": "Cannot resolve standby region", "last_sync": None}

        logger.info(f"DB RPO: peer_db={peer_db_id} standby_region={standby_region}")

        # Step 5 – query DG associations from the standby database in standby region
        standby_db_client = make_client(oci.database.DatabaseClient, standby_region)
        standby_assocs = paginate(
            standby_db_client.list_data_guard_associations,
            database_id=peer_db_id,
        )
        if not standby_assocs:
            return {"rpo": "No standby DG association", "last_sync": None}

        standby_assoc = next(
            (a for a in standby_assocs if a.lifecycle_state == "AVAILABLE"),
            standby_assocs[0]
        )

        # Step 6 – apply_lag is populated on the standby side
        apply_lag = standby_assoc.apply_lag
        logger.info(f"DB RPO: standby apply_lag={apply_lag!r}")

        return {
            "rpo": _parse_apply_lag(apply_lag),
            "last_sync": None,
            "apply_lag_raw": apply_lag,
        }
    except Exception as e:
        logger.warning(f"DB RPO failed for {database_id}: {e}")
        return {"rpo": "Unknown", "last_sync": None}


def _parse_apply_lag(lag_str: str) -> str:
    if not lag_str:
        return "Unknown"
    # Format: "0 days 0 hours 1 minutes 30 seconds"
    parts = {}
    for match in re.finditer(r"(\d+)\s*(day|hour|minute|second)s?", lag_str, re.I):
        parts[match.group(2).lower()] = int(match.group(1))
    td = timedelta(
        days=parts.get("day", 0),
        hours=parts.get("hour", 0),
        minutes=parts.get("minute", 0),
        seconds=parts.get("second", 0),
    )
    return fmt_duration(td)


# ---------------------------------------------------------------------------
# Compute Instance Movable RPO (via Volume Groups)
# ---------------------------------------------------------------------------

def get_compute_instance_rpo(instance_id: str, region: str, compartment_id: str) -> dict:
    """Find volume groups that contain this instance's volumes."""
    try:
        compute = make_client(oci.core.ComputeClient, region)
        blockstorage = make_client(oci.core.BlockstorageClient, region)

        # Get all volume attachments for this instance
        attachments = paginate(
            compute.list_volume_attachments,
            compartment_id=compartment_id,
            instance_id=instance_id,
        )
        volume_ids = {a.volume_id for a in attachments if a.lifecycle_state == "ATTACHED"}

        # Also get boot volume attachments
        boot_attachments = paginate(
            compute.list_boot_volume_attachments,
            availability_domain=_get_instance_ad(compute, instance_id),
            compartment_id=compartment_id,
            instance_id=instance_id,
        )
        boot_volume_ids = {a.boot_volume_id for a in boot_attachments if a.lifecycle_state == "ATTACHED"}

        all_volume_ids = volume_ids | boot_volume_ids

        if not all_volume_ids:
            return {"rpo": "No volumes attached", "last_sync": None}

        # Find volume groups that contain any of these volumes
        vg_rpo = _find_vg_rpo_for_volumes(all_volume_ids, compartment_id, region, blockstorage)
        return vg_rpo
    except Exception as e:
        logger.warning(f"Compute instance RPO failed for {instance_id}: {e}")
        return {"rpo": "Unknown", "last_sync": None}


def _get_instance_ad(compute_client, instance_id: str) -> str:
    try:
        return compute_client.get_instance(instance_id).data.availability_domain
    except Exception:
        return ""


def _find_vg_rpo_for_volumes(volume_ids: set, compartment_id: str, region: str, blockstorage=None) -> dict:
    """Search volume groups in the compartment for any that contain these volumes."""
    if not blockstorage:
        blockstorage = make_client(oci.core.BlockstorageClient, region)
    try:
        vgs = paginate(
            blockstorage.list_volume_groups,
            compartment_id=compartment_id,
        )
        for vg in vgs:
            try:
                vg_detail = blockstorage.get_volume_group(vg.id).data
                vg_volumes = set(vg_detail.volume_ids or [])
                if vg_volumes & volume_ids:
                    return get_volume_group_rpo_v2(vg.id, region)
            except Exception:
                pass
        return {"rpo": "No matching VG", "last_sync": None}
    except Exception as e:
        logger.warning(f"VG search failed: {e}")
        return {"rpo": "Unknown", "last_sync": None}


# ---------------------------------------------------------------------------
# OKE Cluster RPO (via node volume groups)
# ---------------------------------------------------------------------------

def get_oke_rpo(oke_cluster_id: str, region: str, compartment_id: str) -> dict:
    try:
        oke_client = make_client(oci.container_engine.ContainerEngineClient, region)
        compute = make_client(oci.core.ComputeClient, region)
        blockstorage = make_client(oci.core.BlockstorageClient, region)

        # List node pools for the cluster
        node_pools = paginate(
            oke_client.list_node_pools,
            compartment_id=compartment_id,
            cluster_id=oke_cluster_id,
        )

        all_volume_ids = set()
        for np in node_pools:
            try:
                np_detail = oke_client.get_node_pool(np.id).data
                for node in (np_detail.nodes or []):
                    if node.lifecycle_state in ("ACTIVE", "UPDATING"):
                        instance_id = node.id
                        # Get volumes for this node/instance
                        attachments = paginate(
                            compute.list_volume_attachments,
                            compartment_id=compartment_id,
                            instance_id=instance_id,
                        )
                        all_volume_ids.update(
                            a.volume_id for a in attachments if a.lifecycle_state == "ATTACHED"
                        )
                        try:
                            ad = _get_instance_ad(compute, instance_id)
                            boot_attachments = paginate(
                                compute.list_boot_volume_attachments,
                                availability_domain=ad,
                                compartment_id=compartment_id,
                                instance_id=instance_id,
                            )
                            all_volume_ids.update(
                                a.boot_volume_id for a in boot_attachments
                                if a.lifecycle_state == "ATTACHED"
                            )
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Node pool processing failed: {e}")

        if not all_volume_ids:
            return {"rpo": "No node volumes found", "last_sync": None}

        return _find_vg_rpo_for_volumes(all_volume_ids, compartment_id, region, blockstorage)
    except Exception as e:
        logger.warning(f"OKE RPO failed for {oke_cluster_id}: {e}")
        return {"rpo": "Unknown", "last_sync": None}


# ---------------------------------------------------------------------------
# MySQL DB System RPO
# ---------------------------------------------------------------------------

_MYSQL_WR_POLL_INTERVAL = 3   # seconds between work-request polls
_MYSQL_WR_MAX_POLLS     = 20  # give up after ~60 s

def get_mysql_rpo(mysql_id: str, region: str) -> dict:
    """
    MySQL Channel lag via Generate Channel Status:
      1. Get the DB System → compartment_id
      2. list_channels(compartment_id, db_system_id=mysql_id) → find ACTIVE channels
      3. generate_channel_status(channel_id) → async work request
         The work-request ID is in the response header 'opc-work-request-id'.
      4. Poll get_work_request(wr_id) until status == SUCCEEDED
      5. get_channel_status(channel_id) → channel_status_result.lag_duration
      Pick the worst (largest) lag across all channels.
    """
    try:
        mysql_db_client  = make_client(oci.mysql.DbSystemClient, region)
        channels_client  = make_client(oci.mysql.ChannelsClient, region)
        wr_client        = make_client(oci.mysql.WorkRequestsClient, region)

        # Step 1 – compartment_id
        db = mysql_db_client.get_db_system(mysql_id).data
        compartment_id = db.compartment_id

        # Step 2 – list channels targeting this DB System
        channels = paginate(
            channels_client.list_channels,
            compartment_id=compartment_id,
            db_system_id=mysql_id,
        )
        active_channels = [c for c in channels if c.lifecycle_state == "ACTIVE"]
        if not active_channels:
            return {"rpo": "No active channel", "last_sync": None}

        worst_lag_seconds = -1
        worst_lag_str = None

        for channel in active_channels:
            channel_id = channel.id
            try:
                # Step 3 – trigger status generation; capture work-request ID from header
                gen_response = channels_client.generate_channel_status(channel_id)
                wr_id = gen_response.headers.get("opc-work-request-id")

                # Step 4 – poll work request until SUCCEEDED
                if wr_id:
                    for _ in range(_MYSQL_WR_MAX_POLLS):
                        wr = wr_client.get_work_request(wr_id).data
                        logger.info(f"MySQL channel {channel_id} WR {wr_id} status={wr.status}")
                        if wr.status == "SUCCEEDED":
                            break
                        if wr.status in ("FAILED", "CANCELED"):
                            logger.warning(f"MySQL WR {wr_id} ended with {wr.status}")
                            break
                        time.sleep(_MYSQL_WR_POLL_INTERVAL)

                # Step 5 – read channel status
                status_response = channels_client.get_channel_status(channel_id)
                channel_status = status_response.data
                result = channel_status.channel_status_result
                if result is None:
                    continue

                lag_str = result.lag_duration  # e.g. "00:01:30" or seconds string
                logger.info(f"MySQL channel {channel_id} lag_duration={lag_str!r} healthy={result.is_healthy}")

                # Parse lag_duration — OCI returns it as "HH:MM:SS" or plain seconds string
                lag_seconds = _parse_mysql_lag(lag_str)
                if lag_seconds is not None and lag_seconds > worst_lag_seconds:
                    worst_lag_seconds = lag_seconds
                    worst_lag_str = lag_str

            except Exception as e:
                logger.warning(f"MySQL channel {channel_id} status failed: {e}")

        if worst_lag_seconds < 0:
            return {"rpo": "Unknown", "last_sync": None}

        return {
            "rpo": fmt_duration(timedelta(seconds=worst_lag_seconds)),
            "last_sync": None,
            "lag_raw": worst_lag_str,
        }
    except Exception as e:
        logger.warning(f"MySQL RPO failed for {mysql_id}: {e}")
        return {"rpo": "Unknown", "last_sync": None}


def _parse_mysql_lag(lag_str: str):
    """
    Parse MySQL lag_duration string → total seconds (int).
    OCI may return:
      - "HH:MM:SS"    e.g. "00:01:30"
      - plain integer string of seconds  e.g. "90"
      - ISO-8601 duration  e.g. "PT1M30S"
    Returns None if unparseable.
    """
    if not lag_str:
        return None
    lag_str = lag_str.strip()

    # HH:MM:SS
    m = re.fullmatch(r'(\d+):(\d{2}):(\d{2})', lag_str)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))

    # Plain seconds
    if re.fullmatch(r'\d+', lag_str):
        return int(lag_str)

    # ISO-8601 PT#H#M#S
    m = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', lag_str, re.I)
    if m:
        h = int(m.group(1) or 0)
        mn = int(m.group(2) or 0)
        s = int(float(m.group(3) or 0))
        return h * 3600 + mn * 60 + s

    return None


# ---------------------------------------------------------------------------
# Member display-name lookup
# ---------------------------------------------------------------------------

def get_member_name(member_id: str, member_type: str, region: str) -> str:
    """Return the human-readable name for a DRPG member resource."""
    try:
        if member_type in ("COMPUTE_INSTANCE", "COMPUTE_INSTANCE_MOVABLE", "COMPUTE_INSTANCE_NON_MOVABLE"):
            c = make_client(oci.core.ComputeClient, region)
            return c.get_instance(member_id).data.display_name

        elif member_type == "VOLUME_GROUP":
            bs = make_client(oci.core.BlockstorageClient, region)
            return bs.get_volume_group(member_id).data.display_name

        elif member_type == "FILE_SYSTEM":
            fs = make_client(oci.file_storage.FileStorageClient, region)
            return fs.get_file_system(member_id).data.display_name

        elif member_type == "DATABASE":
            db = make_client(oci.database.DatabaseClient, region)
            # member_id may be a DB System or Database OCID
            try:
                return db.get_db_system(member_id).data.display_name
            except Exception:
                return db.get_database(member_id).data.db_unique_name

        elif member_type == "AUTONOMOUS_DATABASE":
            db = make_client(oci.database.DatabaseClient, region)
            return db.get_autonomous_database(member_id).data.display_name

        elif member_type == "AUTONOMOUS_CONTAINER_DATABASE":
            db = make_client(oci.database.DatabaseClient, region)
            return db.get_autonomous_container_database(member_id).data.display_name

        elif member_type == "MYSQL_DB_SYSTEM":
            mysql = make_client(oci.mysql.DbSystemClient, region)
            return mysql.get_db_system(member_id).data.display_name

        elif member_type == "OKE_CLUSTER":
            oke = make_client(oci.container_engine.ContainerEngineClient, region)
            return oke.get_cluster(member_id).data.name

        elif member_type == "LOAD_BALANCER":
            lb = make_client(oci.load_balancer.LoadBalancerClient, region)
            return lb.get_load_balancer(member_id).data.display_name

        elif member_type == "NETWORK_LOAD_BALANCER":
            nlb = make_client(oci.network_load_balancer.NetworkLoadBalancerClient, region)
            return nlb.get_network_load_balancer(member_id).data.display_name

        elif member_type == "OBJECT_STORAGE_BUCKET":
            # member_id for buckets is the bucket name, not an OCID
            return member_id

        elif member_type == "INTEGRATION_INSTANCE":
            integ = make_client(oci.integration.IntegrationInstanceClient, region)
            return integ.get_integration_instance(member_id).data.display_name

        else:
            return member_id  # fallback: show the OCID
    except Exception as e:
        logger.warning(f"Name lookup failed for {member_id} ({member_type}): {e}")
        return member_id  # fallback: show the OCID


# ---------------------------------------------------------------------------
# Member lifecycle-state lookup
# ---------------------------------------------------------------------------

def get_member_state(member_id: str, member_type: str, region: str) -> str:
    """Fetch the current lifecycle_state of a DRPG member resource."""
    try:
        if member_type in ("COMPUTE_INSTANCE", "COMPUTE_INSTANCE_MOVABLE", "COMPUTE_INSTANCE_NON_MOVABLE"):
            c = make_client(oci.core.ComputeClient, region)
            return c.get_instance(member_id).data.lifecycle_state

        elif member_type == "VOLUME_GROUP":
            bs = make_client(oci.core.BlockstorageClient, region)
            return bs.get_volume_group(member_id).data.lifecycle_state

        elif member_type == "FILE_SYSTEM":
            fs = make_client(oci.file_storage.FileStorageClient, region)
            return fs.get_file_system(member_id).data.lifecycle_state

        elif member_type == "DATABASE":
            db = make_client(oci.database.DatabaseClient, region)
            try:
                return db.get_database(member_id).data.lifecycle_state
            except Exception:
                return db.get_db_system(member_id).data.lifecycle_state

        elif member_type == "AUTONOMOUS_DATABASE":
            db = make_client(oci.database.DatabaseClient, region)
            return db.get_autonomous_database(member_id).data.lifecycle_state

        elif member_type == "AUTONOMOUS_CONTAINER_DATABASE":
            db = make_client(oci.database.DatabaseClient, region)
            return db.get_autonomous_container_database(member_id).data.lifecycle_state

        elif member_type == "MYSQL_DB_SYSTEM":
            mysql = make_client(oci.mysql.DbSystemClient, region)
            return mysql.get_db_system(member_id).data.lifecycle_state

        elif member_type == "OKE_CLUSTER":
            oke = make_client(oci.container_engine.ContainerEngineClient, region)
            return oke.get_cluster(member_id).data.lifecycle_state

        elif member_type == "LOAD_BALANCER":
            lb = make_client(oci.load_balancer.LoadBalancerClient, region)
            return lb.get_load_balancer(member_id).data.lifecycle_state

        elif member_type == "NETWORK_LOAD_BALANCER":
            nlb = make_client(oci.network_load_balancer.NetworkLoadBalancerClient, region)
            return nlb.get_network_load_balancer(member_id).data.lifecycle_state

        elif member_type == "INTEGRATION_INSTANCE":
            integ = make_client(oci.integration.IntegrationInstanceClient, region)
            return integ.get_integration_instance(member_id).data.lifecycle_state

        else:
            return None
    except Exception as e:
        logger.warning(f"State lookup failed for {member_id} ({member_type}): {e}")
        return None


# ---------------------------------------------------------------------------
# Member RPO dispatcher
# ---------------------------------------------------------------------------

def get_member_rpo(member: dict, region: str, compartment_id: str) -> dict:
    member_type = member.get("member_type", "")
    member_id = member.get("member_id", "")

    if member_type == "VOLUME_GROUP":
        return get_volume_group_rpo_v2(member_id, region)
    elif member_type == "FILE_SYSTEM":
        return get_filesystem_rpo(member_id, region)
    elif member_type in ("COMPUTE_INSTANCE_MOVABLE", "COMPUTE_INSTANCE", "COMPUTE_INSTANCE_NON_MOVABLE"):
        return get_compute_instance_rpo(member_id, region, compartment_id)
    elif member_type in ("DATABASE", "AUTONOMOUS_DATABASE", "AUTONOMOUS_CONTAINER_DATABASE"):
        return get_database_rpo(member_id, region)
    elif member_type == "MYSQL_DB_SYSTEM":
        return get_mysql_rpo(member_id, region)
    elif member_type == "OKE_CLUSTER":
        return get_oke_rpo(member_id, region, compartment_id)
    else:
        # LOAD_BALANCER, NETWORK_LOAD_BALANCER, OBJECT_STORAGE_BUCKET, INTEGRATION_INSTANCE
        # are stateless or managed by OCI — RPO is not applicable
        return {"rpo": "N/A", "last_sync": None}


# ---------------------------------------------------------------------------
# RTO Calculation
# ---------------------------------------------------------------------------

def get_drpg_rto(drpg_id: str, region: str) -> dict:
    """
    Get RTO from the *standby* DRPG's START_DRILL plan executions.

    Flow:
      1. Fetch the primary DRPG to find its peer_id (standby DRPG) and peer_region.
      2. List plan executions on the standby DRPG in the peer region.
      3. Filter for START_DRILL type; pick the latest completed one.
      4. Return its duration.
    """
    try:
        dr_client = make_client(oci.disaster_recovery.DisasterRecoveryClient, region)

        # Step 1 – resolve standby DRPG coordinates from the primary
        primary = dr_client.get_dr_protection_group(drpg_id).data
        standby_id = getattr(primary, 'peer_id', None)
        standby_region = getattr(primary, 'peer_region', None)

        if not standby_id or not standby_region:
            return {"rto": "Unknown (no standby peer)", "last_execution": None,
                    "standby_region": None}

        # Step 2 – query executions on the standby DRPG in the peer region
        standby_dr_client = make_client(
            oci.disaster_recovery.DisasterRecoveryClient, standby_region
        )
        executions = paginate(
            standby_dr_client.list_dr_plan_executions,
            dr_protection_group_id=standby_id,
        )

        # Step 3 – filter: START_DRILL + terminal state
        _terminal = {"SUCCEEDED", "FAILED", "CANCELED"}
        drill_executions = [
            e for e in executions
            if getattr(e, 'plan_execution_type', '') == "START_DRILL"
            and e.lifecycle_state in _terminal
        ]

        if not drill_executions:
            return {"rto": "Unknown", "last_execution": None,
                    "standby_region": standby_region}

        # Step 4 – sort newest first
        drill_executions.sort(
            key=lambda e: e.time_started or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        latest = drill_executions[0]

        # Calculate duration
        duration = None
        if latest.time_started and latest.time_ended:
            ts = latest.time_started
            te = latest.time_ended
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if te.tzinfo is None:
                te = te.replace(tzinfo=timezone.utc)
            duration = te - ts

        return {
            "rto": fmt_duration(duration) if duration else "Unknown",
            "last_execution": serialize(latest),
            "execution_state": latest.lifecycle_state,
            "standby_region": standby_region,
        }
    except Exception as e:
        logger.warning(f"RTO calculation failed for {drpg_id}: {e}")
        return {"rto": "Unknown", "last_execution": None, "standby_region": None}


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/api/regions", methods=["GET"])
@require_auth
def list_regions():
    """Return the list of OCI regions."""
    try:
        config, signer = get_config_and_signer()
        if signer:
            identity = oci.identity.IdentityClient(config={}, signer=signer)
        else:
            identity = oci.identity.IdentityClient(config)
        regions = identity.list_regions().data
        return jsonify([{"name": r.name, "key": r.key} for r in regions])
    except Exception as e:
        logger.error(f"/api/regions error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/compartments", methods=["GET"])
@require_auth
def list_compartments():
    """Return the list of compartments accessible to the user."""
    try:
        config, signer = get_config_and_signer()
        if signer:
            identity = oci.identity.IdentityClient(config={}, signer=signer)
        else:
            identity = oci.identity.IdentityClient(config)

        # Get tenancy OCID
        tenancy_id = config.get("tenancy") if config.get("tenancy") else signer.tenancy_id

        compartments = paginate(
            identity.list_compartments,
            compartment_id=tenancy_id,
            compartment_id_in_subtree=True,
            access_level="ACCESSIBLE",
        )
        # Include root
        result = [{"id": tenancy_id, "name": "/ (root)", "lifecycle_state": "ACTIVE"}]
        result += [
            {
                "id": c.id,
                "name": c.name,
                "lifecycle_state": c.lifecycle_state,
            }
            for c in compartments
            if c.lifecycle_state == "ACTIVE"
        ]
        return jsonify(result)
    except Exception as e:
        logger.error(f"/api/compartments error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/drpgs", methods=["GET"])
@require_auth
def list_drpgs():
    """List primary DR Protection Groups for a region and compartment."""
    region = request.args.get("region")
    compartment_id = request.args.get("compartment_id")
    if not region or not compartment_id:
        return jsonify({"error": "region and compartment_id are required"}), 400

    try:
        dr_client = make_client(oci.disaster_recovery.DisasterRecoveryClient, region)
        drpgs = paginate(
            dr_client.list_dr_protection_groups,
            compartment_id=compartment_id,
        )

        # Only return PRIMARY DRPGs
        primary_drpgs = []
        for drpg in drpgs:
            role = getattr(drpg, "role", None)
            if role == "PRIMARY":
                primary_drpgs.append({
                    "id": drpg.id,
                    "display_name": drpg.display_name,
                    "lifecycle_state": drpg.lifecycle_state,
                    "role": role,
                    "time_created": serialize(drpg.time_created),
                    "time_updated": serialize(drpg.time_updated),
                    "peer_id": getattr(drpg, "peer_id", None),
                    "peer_region": getattr(drpg, "peer_region", None),
                })

        return jsonify(primary_drpgs)
    except Exception as e:
        logger.error(f"/api/drpgs error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/drpgs/<drpg_id>/plans", methods=["GET"])
@require_auth
def list_plans(drpg_id):
    """List DR plans for a DRPG, including standby peer plans."""
    region = request.args.get("region")
    if not region:
        return jsonify({"error": "region is required"}), 400

    def _serialize_plan(plan, source, drpg_id, region):
        return {
            "id": plan.id,
            "display_name": plan.display_name,
            "type": getattr(plan, "type", None),
            "lifecycle_state": plan.lifecycle_state,
            "time_created": serialize(plan.time_created),
            "time_updated": serialize(plan.time_updated),
            "source": source,
            "drpg_id": drpg_id,
            "region": region,
        }

    try:
        dr_client = make_client(oci.disaster_recovery.DisasterRecoveryClient, region)

        # Resolve peer info from the primary DRPG
        drpg = dr_client.get_dr_protection_group(drpg_id).data
        peer_id     = getattr(drpg, "peer_id", None)
        peer_region = getattr(drpg, "peer_region", None)

        result = []

        # Primary plans
        for plan in paginate(dr_client.list_dr_plans, dr_protection_group_id=drpg_id):
            result.append(_serialize_plan(plan, "PRIMARY", drpg_id, region))

        # Standby plans
        if peer_id and peer_region:
            try:
                standby_dr = make_client(oci.disaster_recovery.DisasterRecoveryClient, peer_region)
                for plan in paginate(standby_dr.list_dr_plans, dr_protection_group_id=peer_id):
                    result.append(_serialize_plan(plan, "STANDBY", peer_id, peer_region))
            except Exception as e:
                logger.warning(f"Could not fetch standby plans: {e}")

        return jsonify(result)
    except Exception as e:
        logger.error(f"/api/drpgs/{drpg_id}/plans error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/drpgs/<drpg_id>/members", methods=["GET"])
@require_auth
def list_members(drpg_id):
    """List members of a DRPG with their RPO info."""
    region = request.args.get("region")
    compartment_id = request.args.get("compartment_id")
    if not region:
        return jsonify({"error": "region is required"}), 400

    try:
        dr_client = make_client(oci.disaster_recovery.DisasterRecoveryClient, region)
        drpg = dr_client.get_dr_protection_group(drpg_id).data

        if not compartment_id:
            compartment_id = drpg.compartment_id

        peer_id     = getattr(drpg, "peer_id", None)
        peer_region = getattr(drpg, "peer_region", None)

        # Build a map of member_type → list of standby member OCIDs so that
        # member types whose RPO must be read from the standby (e.g. MYSQL_DB_SYSTEM)
        # can be redirected to the correct resource and region.
        peer_member_map: dict = {}   # {member_type: [ocid, ...]}
        if peer_id and peer_region:
            try:
                standby_dr = make_client(
                    oci.disaster_recovery.DisasterRecoveryClient, peer_region
                )
                standby_drpg = standby_dr.get_dr_protection_group(peer_id).data
                for sm in (getattr(standby_drpg, "members", []) or []):
                    peer_member_map.setdefault(sm.member_type, []).append(sm.member_id)
            except Exception as e:
                logger.warning(f"Could not fetch standby DRPG members: {e}")

        members_raw = getattr(drpg, "members", []) or []
        members = []
        for m in members_raw:
            members.append({
                "member_id": m.member_id,
                "member_type": m.member_type,
            })

        # Fetch name + state + RPO in parallel for each member
        def fetch_member_details(member):
            mid   = member["member_id"]
            mtype = member["member_type"]
            name  = get_member_name(mid, mtype, region)
            state = get_member_state(mid, mtype, region)

            # MySQL channels live on the standby DB System — redirect RPO lookup
            if mtype == "MYSQL_DB_SYSTEM" and peer_region:
                standby_mysql_ids = peer_member_map.get("MYSQL_DB_SYSTEM", [])
                if standby_mysql_ids:
                    rpo_info = get_mysql_rpo(standby_mysql_ids[0], peer_region)
                else:
                    rpo_info = {"rpo": "No standby MySQL found", "last_sync": None}
            else:
                rpo_info = get_member_rpo(member, region, compartment_id)

            return {**member, "display_name": name, "lifecycle_state": state, **rpo_info}

        enriched = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(fetch_member_details, m): m for m in members}
            for future in as_completed(futures):
                try:
                    enriched.append(future.result())
                except Exception as e:
                    m = futures[future]
                    enriched.append({**m, "display_name": m["member_id"],
                                     "lifecycle_state": None,
                                     "rpo": "Error", "last_sync": None})

        return jsonify(enriched)
    except Exception as e:
        logger.error(f"/api/drpgs/{drpg_id}/members error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/drpgs/<drpg_id>/rto", methods=["GET"])
@require_auth
def get_rto(drpg_id):
    """Get Last RTO for a DRPG based on last START_DRILL execution."""
    region = request.args.get("region")
    if not region:
        return jsonify({"error": "region is required"}), 400

    try:
        rto_info = get_drpg_rto(drpg_id, region)
        return jsonify(rto_info)
    except Exception as e:
        logger.error(f"/api/drpgs/{drpg_id}/rto error: {e}")
        return jsonify({"error": str(e)}), 500


def _execution_duration(time_started, time_ended):
    """Return a human-readable duration string, or None."""
    if not time_started or not time_ended:
        return None
    delta = time_ended - time_started
    total = int(delta.total_seconds())
    if total < 0:
        return None
    h, rem = divmod(total, 3600)
    m, s   = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


@app.route("/api/drpgs/<drpg_id>/executions", methods=["GET"])
@require_auth
def list_executions(drpg_id):
    """List plan executions for a DRPG, optionally filtered by plan_id."""
    region  = request.args.get("region")
    plan_id = request.args.get("plan_id")
    if not region:
        return jsonify({"error": "region is required"}), 400

    try:
        dr_client = make_client(oci.disaster_recovery.DisasterRecoveryClient, region)
        executions = paginate(
            dr_client.list_dr_plan_executions,
            dr_protection_group_id=drpg_id,
        )
        if plan_id:
            executions = [e for e in executions if e.plan_id == plan_id]
        result = []
        for e in executions:
            result.append({
                "id": e.id,
                "display_name": e.display_name,
                "plan_id": e.plan_id,
                "plan_execution_type": getattr(e, "plan_execution_type", None),
                "lifecycle_state": e.lifecycle_state,
                "time_started": serialize(e.time_started),
                "time_ended": serialize(e.time_ended),
                "duration": _execution_duration(e.time_started, e.time_ended),
            })
        return jsonify(result)
    except Exception as e:
        logger.error(f"/api/drpgs/{drpg_id}/executions error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/executions/<execution_id>", methods=["GET"])
@require_auth
def get_execution_detail(execution_id):
    """Get detailed execution info including step-by-step breakdown."""
    region = request.args.get("region")
    if not region:
        return jsonify({"error": "region is required"}), 400

    try:
        dr_client = make_client(oci.disaster_recovery.DisasterRecoveryClient, region)
        execution = dr_client.get_dr_plan_execution(execution_id).data

        groups = []
        for grp in (getattr(execution, "plan_execution_groups", []) or []):
            steps = []
            for step in (getattr(grp, "steps", []) or []):
                steps.append({
                    "id": step.id,
                    "display_name": step.display_name,
                    "type": getattr(step, "type", None),
                    "status": getattr(step, "status", None),
                    "time_started": serialize(getattr(step, "time_started", None)),
                    "time_ended":   serialize(getattr(step, "time_ended", None)),
                    "execution_duration_in_sec": getattr(step, "execution_duration_in_sec", None),
                    "error_message": getattr(step, "error_message", None),
                })
            groups.append({
                "id": grp.id,
                "display_name": grp.display_name,
                "type": getattr(grp, "type", None),
                "status": getattr(grp, "status", None),
                "time_started": serialize(getattr(grp, "time_started", None)),
                "time_ended":   serialize(getattr(grp, "time_ended", None)),
                "execution_duration_in_sec": getattr(grp, "execution_duration_in_sec", None),
                "steps": steps,
            })

        return jsonify({
            "id": execution.id,
            "display_name": execution.display_name,
            "plan_id": execution.plan_id,
            "plan_execution_type": getattr(execution, "plan_execution_type", None),
            "lifecycle_state": execution.lifecycle_state,
            "time_started": serialize(execution.time_started),
            "time_ended": serialize(execution.time_ended),
            "duration": _execution_duration(execution.time_started, execution.time_ended),
            "groups": groups,
        })
    except Exception as e:
        logger.error(f"/api/executions/{execution_id} error: {e}")
        return jsonify({"error": str(e)}), 500


_PRECHECK_TYPE_MAP = {
    "SWITCHOVER":  "SWITCHOVER_PRECHECK",
    "FAILOVER":    "FAILOVER_PRECHECK",
    "START_DRILL": "START_DRILL_PRECHECK",
    "STOP_DRILL":  "STOP_DRILL_PRECHECK",
}

# Maps each precheck execution type to its SDK ExecutionOptionDetails model class name
_PRECHECK_OPTIONS_CLASS = {
    "SWITCHOVER_PRECHECK":  "SwitchoverPrecheckExecutionOptionDetails",
    "FAILOVER_PRECHECK":    "FailoverPrecheckExecutionOptionDetails",
    "START_DRILL_PRECHECK": "StartDrillPrecheckExecutionOptionDetails",
    "STOP_DRILL_PRECHECK":  "StopDrillPrecheckExecutionOptionDetails",
}


@app.route("/api/plans/<plan_id>/precheck", methods=["POST"])
@require_auth
def run_precheck(plan_id):
    """Trigger a precheck execution for a DR plan."""
    body        = request.get_json(force=True) or {}
    region      = body.get("region")
    drpg_id     = body.get("drpg_id")
    plan_type   = body.get("plan_type")
    display_name = body.get("display_name")

    if not region:
        return jsonify({"error": "region is required"}), 400
    if not drpg_id:
        return jsonify({"error": "drpg_id is required"}), 400

    execution_type = _PRECHECK_TYPE_MAP.get(plan_type)
    if not execution_type:
        return jsonify({"error": f"Cannot run precheck for plan type: {plan_type}"}), 400

    try:
        dr_client = make_client(oci.disaster_recovery.DisasterRecoveryClient, region)

        # Build execution options — required by the API
        opts_class_name = _PRECHECK_OPTIONS_CLASS.get(execution_type)
        opts_class = getattr(oci.disaster_recovery.models, opts_class_name, None)
        if opts_class is None:
            return jsonify({"error": f"No execution options model found for {execution_type}"}), 500
        exec_opts = opts_class()
        exec_opts.plan_execution_type = execution_type

        details = oci.disaster_recovery.models.CreateDrPlanExecutionDetails()
        details.display_name = display_name or f"Precheck – {plan_type}"
        details.plan_id = plan_id
        details.plan_execution_type = execution_type
        details.execution_options = exec_opts
        execution = dr_client.create_dr_plan_execution(
            create_dr_plan_execution_details=details
        ).data
        return jsonify({
            "id": execution.id,
            "display_name": execution.display_name,
            "lifecycle_state": execution.lifecycle_state,
            "plan_execution_type": getattr(execution, "plan_execution_type", None),
            "time_started": serialize(getattr(execution, "time_started", None)),
        }), 201
    except Exception as e:
        logger.error(f"/api/plans/{plan_id}/precheck error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
