"""Authenticated delivery of camera-by-camera people count batches."""
from relleno.portal import agent_post


def send_batch(binding, batch):
    data = agent_post(binding, 'people_count_url', batch)
    receipt = data.get('receipt') or {}
    receipt_id = receipt.get('id')
    if not receipt_id:
        raise ValueError('El portal no confirmó la recepción de Personas.')
    return str(receipt_id)
