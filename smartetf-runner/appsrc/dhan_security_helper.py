"""
DHAN Security Helper - Add to app.py or import as needed
Provides encryption/decryption for DHAN client_id and api_key
"""

from security_utils import encrypt_portal_password, decrypt_portal_password


def encrypt_dhan_client_id(plaintext):
    if not plaintext:
        return None, None, None
    return encrypt_portal_password(plaintext)


def decrypt_dhan_client_id(cipher_b64, iv_b64, tag_b64):
    if not cipher_b64 or not iv_b64 or not tag_b64:
        return None
    return decrypt_portal_password(cipher_b64, iv_b64, tag_b64)


def encrypt_dhan_api_key(plaintext):
    if not plaintext:
        return None, None, None
    return encrypt_portal_password(plaintext)


def decrypt_dhan_api_key(cipher_b64, iv_b64, tag_b64):
    if not cipher_b64 or not iv_b64 or not tag_b64:
        return None
    return decrypt_portal_password(cipher_b64, iv_b64, tag_b64)


def prepare_dhan_broker_for_save(broker, client_id=None, api_key=None):
    """Encrypt and save DHAN credentials to broker model"""
    if client_id:
        enc, iv, tag = encrypt_dhan_client_id(client_id)
        broker.dhan_client_id_enc = enc
        broker.dhan_client_id_iv = iv
        broker.dhan_client_id_tag = tag
    
    if api_key and broker.broker_name.upper() == 'DHAN':
        enc, iv, tag = encrypt_dhan_api_key(api_key)
        broker.api_key_enc = enc
        broker.api_key_iv = iv
        broker.api_key_tag = tag
        broker.api_key = None
    elif api_key:
        broker.api_key = api_key


def get_decrypted_dhan_credentials(broker):
    """Get decrypted DHAN credentials from broker model"""
    result = {}
    
    if broker.dhan_client_id_enc:
        result['dhan_client_id'] = decrypt_dhan_client_id(
            broker.dhan_client_id_enc,
            broker.dhan_client_id_iv,
            broker.dhan_client_id_tag
        )
    
    if broker.broker_name.upper() == 'DHAN' and broker.api_key_enc:
        result['api_key'] = decrypt_dhan_api_key(
            broker.api_key_enc,
            broker.api_key_iv,
            broker.api_key_tag
        )
    else:
        result['api_key'] = broker.api_key
    
    return result
