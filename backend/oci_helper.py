import oci
import logging
import socket

logger = logging.getLogger(__name__)

_instance_principal_signer = None
_use_instance_principal = None

# OCI instance metadata service IP & port
_IMDS_HOST = "169.254.169.254"
_IMDS_PORT = 80
_IMDS_TIMEOUT = 1.0  # seconds — fast probe before attempting full IP auth


def _is_running_on_oci() -> bool:
    """Quick TCP probe to check if the OCI metadata endpoint is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(_IMDS_TIMEOUT)
        result = sock.connect_ex((_IMDS_HOST, _IMDS_PORT))
        sock.close()
        return result == 0
    except Exception:
        return False


def _detect_auth_method():
    global _use_instance_principal, _instance_principal_signer
    if _use_instance_principal is not None:
        return _use_instance_principal

    if not _is_running_on_oci():
        logger.info("IMDS not reachable — using OCI config file authentication")
        _use_instance_principal = False
        return _use_instance_principal

    try:
        _instance_principal_signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        _use_instance_principal = True
        logger.info("Using Instance Principal authentication")
    except Exception as e:
        logger.info(f"Instance Principal not available ({e}), falling back to OCI config file")
        _use_instance_principal = False

    return _use_instance_principal


def get_config_and_signer(region=None):
    use_ip = _detect_auth_method()
    if use_ip:
        signer = _instance_principal_signer
        config = {}
        if region:
            config['region'] = region
        return config, signer
    else:
        config = oci.config.from_file()
        if region:
            config = dict(config)
            config['region'] = region
        return config, None


def make_client(client_class, region=None):
    config, signer = get_config_and_signer(region)
    if signer:
        return client_class(config=config, signer=signer)
    return client_class(config)


def paginate(client_fn, **kwargs):
    """Collect all pages from a list call."""
    results = []
    response = client_fn(**kwargs)
    results.extend(response.data.items if hasattr(response.data, 'items') else response.data)
    while response.has_next_page:
        kwargs['page'] = response.next_page
        response = client_fn(**kwargs)
        results.extend(response.data.items if hasattr(response.data, 'items') else response.data)
    return results
