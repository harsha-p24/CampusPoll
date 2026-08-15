"""
Secrets abstraction layer.

Supports multiple backends:
  - Environment variables (default, works everywhere)
  - AWS Secrets Manager (set SECRETS_BACKEND=aws)
  - HashiCorp Vault (set SECRETS_BACKEND=vault)
  - GCP Secret Manager (set SECRETS_BACKEND=gcp)

Usage:
    from services.secrets_service import get_secret
    db_password = get_secret('DATABASE_PASSWORD')
"""
import os
import logging

logger = logging.getLogger(__name__)
_cache: dict = {}


def get_secret(key: str, default: str = '') -> str:
    """
    Retrieve a secret by key.
    Checks cache first, then configured backend, then env vars.
    """
    if key in _cache:
        return _cache[key]

    backend = os.getenv('SECRETS_BACKEND', 'env').lower()

    if backend == 'aws':
        value = _get_aws_secret(key)
    elif backend == 'vault':
        value = _get_vault_secret(key)
    elif backend == 'gcp':
        value = _get_gcp_secret(key)
    else:
        value = os.getenv(key, default)

    if value:
        _cache[key] = value
    return value or default


def _get_aws_secret(key: str) -> str:
    """Fetch from AWS Secrets Manager."""
    try:
        import boto3
        from botocore.exceptions import ClientError
        secret_name = os.getenv('AWS_SECRET_NAME', 'campuspoll/secrets')
        region      = os.getenv('AWS_REGION', 'us-east-1')
        client      = boto3.client('secretsmanager', region_name=region)
        response    = client.get_secret_value(SecretId=secret_name)
        import json
        secrets = json.loads(response.get('SecretString', '{}'))
        return secrets.get(key, os.getenv(key, ''))
    except ImportError:
        logger.warning("boto3 not installed — falling back to env vars")
        return os.getenv(key, '')
    except Exception as e:
        logger.error(f"AWS Secrets Manager error for {key}: {e}")
        return os.getenv(key, '')


def _get_vault_secret(key: str) -> str:
    """Fetch from HashiCorp Vault."""
    try:
        import hvac
        vault_addr  = os.getenv('VAULT_ADDR', 'http://localhost:8200')
        vault_token = os.getenv('VAULT_TOKEN', '')
        vault_path  = os.getenv('VAULT_SECRET_PATH', 'secret/campuspoll')
        client      = hvac.Client(url=vault_addr, token=vault_token)
        response    = client.secrets.kv.read_secret_version(path=vault_path)
        secrets     = response['data']['data']
        return secrets.get(key, os.getenv(key, ''))
    except ImportError:
        logger.warning("hvac not installed — falling back to env vars")
        return os.getenv(key, '')
    except Exception as e:
        logger.error(f"Vault error for {key}: {e}")
        return os.getenv(key, '')


def _get_gcp_secret(key: str) -> str:
    """Fetch from GCP Secret Manager."""
    try:
        from google.cloud import secretmanager
        project_id  = os.getenv('GCP_PROJECT_ID', '')
        secret_id   = f"campuspoll-{key.lower().replace('_', '-')}"
        client      = secretmanager.SecretManagerServiceClient()
        name        = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response    = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except ImportError:
        logger.warning("google-cloud-secret-manager not installed — falling back to env vars")
        return os.getenv(key, '')
    except Exception as e:
        logger.error(f"GCP Secret Manager error for {key}: {e}")
        return os.getenv(key, '')


def clear_cache():
    """Clear the secrets cache (useful in tests)."""
    global _cache
    _cache = {}
