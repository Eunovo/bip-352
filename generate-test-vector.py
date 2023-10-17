#!/usr/bin/env python

import reference
import json
from secp256k1 import *
import bip32
from copy import deepcopy
from importlib import reload
reload(reference)

G = ECKey().set(1).get_pubkey()
sending_test_vectors = []

HRP="sp"

def get_key_pair(index, seed=b'deadbeef', derivation='m/0h'):

    master = bip32.BIP32.from_seed(seed)
    d = ECKey().set(master.get_privkey_from_path(f'{derivation}/{index}'))
    P = d.get_pubkey()

    return d, P

def add_private_keys(inputs, input_priv_keys):
    for x, i in enumerate(inputs):
        i['private_key'] = input_priv_keys[x][0].get_bytes().hex()

    return inputs

def rmd160(in_str):
    h = hashlib.new('ripemd160')
    h.update(reference.sha256(in_str))
    return h.hexdigest()

def encode_hybrid_key(pub_key):
    x = pub_key.get_x()
    y = pub_key.get_y()
    return bytes([0x06 if y % 2 == 0 else 0x07]) + x.to_bytes(32, 'big') + y.to_bytes(32, 'big')

def get_p2pkh_scriptsig(pub_key, priv_key, hybrid=False):
    msg = reference.sha256(b'message')
    sig = priv_key.sign_ecdsa(msg, False).hex()
    s = len(sig) // 2
    if not hybrid:
        pubkey_bytes = bytes([0x21]) + pub_key.get_bytes(False)
    else:
        pubkey_bytes = bytes([0x41]) + encode_hybrid_key(pub_key)

    return f'{s:0x}' + sig + pubkey_bytes.hex()

def get_p2pkh_scriptPubKey(pub_key, hybrid=False):
    if not hybrid:
        pubkey_bytes = pub_key.get_bytes(False)
    else:
        pubkey_bytes = encode_hybrid_key(pub_key)
    return "76a914" + rmd160(pubkey_bytes) + "88ac"

def get_p2tr_witness(priv_key):
    msg = reference.sha256(b'message')
    sig = priv_key.sign_schnorr(msg).hex()
    return serialize_witness_stack([sig])

def get_p2tr_scriptPubKey(pub_key):
    return "5120" + pub_key.get_bytes(True).hex()

def serialize_witness_stack(stack_items):
    stack_size = len(stack_items)
    result = f'{stack_size:02x}'
    for item in stack_items:
        size = len(item) // 2
        result += f'{size:02x}' + item
    return result


def new_test_case():
    recipient =  {
        "given": {
            "inputs": [],
            "outputs": [],
            "key_material": {
                "spend_priv_key": "hex",
                "scan_priv_key": "hex",
            },
            "labels": [],
        },
        "expected": {
            "addresses": [],
            "outputs": [],
        }
    }
    sender = {
        "given": {
            "inputs": [],
            "recipients": []
        },
        "expected": {
            "outputs": []
        }
    }
    test_case = {
        "comment": "",
        "sending": [],
        "receiving": [],
    }
    return sender, recipient, test_case

# In[10]:


def generate_labeled_output_tests():

    msg = reference.sha256(b'message')
    aux = reference.sha256(b'random auxiliary data')
    G = ECKey().set(1).get_pubkey()
    test_cases = []
    outpoints = [
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0),
    ]
    sender_bip32_seed = 'deadbeef'
    i1, I1 = get_key_pair(0, seed=bytes.fromhex(sender_bip32_seed))
    i2, I2 = get_key_pair(1, seed=bytes.fromhex(sender_bip32_seed))
    input_priv_keys = [(i1, False), (i2, False)]
    input_pub_keys = [I1, I2]

    recipient_bip32_seed = 'f00dbabe'
    label_ints = [(2).to_bytes(32, 'big').hex(),(3).to_bytes(32, 'big').hex(),(1001337).to_bytes(32, 'big').hex()]
    recipient_labels = [[(bytes.fromhex(label_int)*G).get_bytes(False).hex(), label_int] for label_int in label_ints]
    b_scan, b_spend, B_scan, B_spend = reference.derive_silent_payment_key_pair(bytes.fromhex(recipient_bip32_seed))

    address = reference.encode_silent_payment_address(B_scan, B_spend, hrp=HRP)
    labeled_addresses = [
        reference.create_labeled_silent_payment_address(B_scan, B_spend, bytes.fromhex(case), hrp=HRP) for case in label_ints
    ]
    recipient_addresses = [address] + labeled_addresses
    comments = ["Receiving with labels: label with even parity", "Receiving with labels: label with odd parity", "Receiving with labels: large label integer"]
    for i, case in enumerate(label_ints):
        sender, recipient, test_case = new_test_case()
        address = reference.create_labeled_silent_payment_address(B_scan, B_spend, bytes.fromhex(case), hrp=HRP)
        addresses = [(address, 1.0)]

        inputs = []
        for i, outpoint in enumerate(outpoints):
            inputs += [{
                'prevout': list(outpoint) + [get_p2pkh_scriptsig(input_pub_keys[i], input_priv_keys[i][0]), ""],
                'scriptPubKey': get_p2pkh_scriptPubKey(input_pub_keys[i]),
            }]
    
        sender['given']['inputs'] = add_private_keys(deepcopy(inputs), input_priv_keys)
        sender['given']['recipients'] = addresses
        recipient['given']['inputs'] = inputs
        recipient['given']['key_material']['scan_priv_key'] = b_scan.get_bytes().hex()
        recipient['given']['key_material']['spend_priv_key'] = b_spend.get_bytes().hex()
        recipient['expected']['addresses'] = recipient_addresses
        recipient['given']['labels'] = recipient_labels

        outpoints_hash = reference.hash_outpoints(outpoints)
        outputs = reference.create_outputs(input_priv_keys, outpoints_hash, addresses, hrp=HRP)
        sender['expected']['outputs'] = outputs
        output_pub_keys = [r[0] for r in outputs]
        recipient['given']['outputs'] = output_pub_keys

        A_sum = sum(input_pub_keys)
        add_to_wallet = reference.scanning(
            b_scan,
            B_spend,
            A_sum,
            outpoints_hash,
            [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
            labels={l[0]:l[1] for l in recipient_labels},
        )
        for o in add_to_wallet:

            pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
            full_private_key = b_spend.add(
                bytes.fromhex(o['priv_key_tweak'])
            )
            if full_private_key.get_pubkey().get_y()%2 != 0:
                full_private_key.negate()

            sig = full_private_key.sign_schnorr(msg, aux)
            assert pubkey.verify_schnorr(sig, msg)
            o['signature'] = sig.hex()

        recipient['expected']['outputs'] = add_to_wallet
        test_case['sending'].extend([sender])
        test_case['receiving'].extend([recipient])
        test_case["comment"] = comments[i]
        test_cases.append(test_case)

    return test_cases


def generate_single_output_outpoint_tests():

    msg = reference.sha256(b'message')
    aux = reference.sha256(b'random auxiliary data')
    G = ECKey().set(1).get_pubkey()
    outpoint_test_cases = [
        [
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0)
        ],
        [
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0),
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0)
        ],
        [
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 3),
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 7)
        ],
        [
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 7),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 3)
        ],
    ]

    sender_bip32_seed = 'deadbeef'
    recipient_bip32_seed = 'f00dbabe'
    i1, I1 = get_key_pair(0, seed=bytes.fromhex(sender_bip32_seed))
    i2, I2 = get_key_pair(1)
    input_priv_keys = [(i1, False), (i2, False)]
    input_pub_keys = [I1, I2]

    test_cases = []
    comments = [
        "Simple send: two inputs",
        "Simple send: two inputs, order reversed",
        "Simple send: two inputs from the same transaction",
        "Simple send: two inputs from the same transaction, order reversed"
    ]
    for i, outpoints in enumerate(outpoint_test_cases):
        sender, recipient, test_case = new_test_case()
        test_case["comment"] = comments[i]

        inputs = []
        for x, outpoint in enumerate(outpoints):
            scriptSig = get_p2pkh_scriptsig(input_pub_keys[x], input_priv_keys[x][0])
            inputs += [{
                "prevout": list(outpoint) + [scriptSig, ""],
                "scriptPubKey": get_p2pkh_scriptPubKey(input_pub_keys[x]),
            }]
        sender['given']['inputs'] = add_private_keys(deepcopy(inputs), input_priv_keys)

        recipient['given']['inputs'] = inputs

        b_scan, b_spend, B_scan, B_spend = reference.derive_silent_payment_key_pair(bytes.fromhex(recipient_bip32_seed))
        recipient['given']['key_material']['scan_priv_key'] = b_scan.get_bytes().hex()
        recipient['given']['key_material']['spend_priv_key'] = b_spend.get_bytes().hex()
        address = reference.encode_silent_payment_address(B_scan, B_spend, hrp=HRP)

        sender['given']['recipients'].extend([(address, 1.0)])
        recipient['expected']['addresses'].extend([address])

        outpoints_hash = reference.hash_outpoints(outpoints)
        outputs = reference.create_outputs(input_priv_keys, outpoints_hash, [(address, 1.0)], hrp=HRP)
        sender['expected']['outputs'] = outputs
        output_pub_keys = [recipient[0] for recipient in outputs]
        recipient['given']['outputs'] = output_pub_keys

        A_sum = sum(input_pub_keys)
        add_to_wallet = reference.scanning(
            b_scan,
            B_spend,
            A_sum,
            reference.hash_outpoints(outpoints),
            [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
        )
        for o in add_to_wallet:

            pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
            full_private_key = b_spend.add(
                bytes.fromhex(o['priv_key_tweak'])
            )
            if full_private_key.get_pubkey().get_y()%2 != 0:
                full_private_key.negate()

            sig = full_private_key.sign_schnorr(msg, aux)
            assert pubkey.verify_schnorr(sig, msg)
            o['signature'] = sig.hex()

        recipient['expected']['outputs'] = add_to_wallet
        test_case['sending'].extend([sender])
        test_case['receiving'].extend([recipient])
        test_cases.append(test_case)

    return test_cases


def generate_multiple_output_tests():

    msg = reference.sha256(b'message')
    aux = reference.sha256(b'random auxiliary data')
    G = ECKey().set(1).get_pubkey()
    recipient_test_cases = []
    outpoints = [
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0),
    ]
    sender_bip32_seed = 'deadbeef'
    i1, I1 = get_key_pair(0, seed=bytes.fromhex(sender_bip32_seed))
    i2, I2 = get_key_pair(1, seed=bytes.fromhex(sender_bip32_seed))
    input_priv_keys = [(i1, False), (i2, False)]
    input_pub_keys = [I1, I2]

    recipient_one_bip32_seed = 'f00dbabe'
    recipient_two_bip32_seed = 'decafbad'

    scan1, spend1, Scan1, Spend1 = reference.derive_silent_payment_key_pair(bytes.fromhex(recipient_one_bip32_seed))
    address1 = reference.encode_silent_payment_address(Scan1, Spend1, hrp=HRP)
    addresses1 = [(address1, amount) for amount in [2.0, 3.0]]

    scan2, spend2, Scan2, Spend2 = reference.derive_silent_payment_key_pair(bytes.fromhex(recipient_two_bip32_seed))
    address2 = reference.encode_silent_payment_address(Scan2, Spend2, hrp=HRP)
    addresses2 = [(address2, amount) for amount in [4.0, 5.0]]

    test_cases = []

    sender, recipient1, test_case = new_test_case()
    sender1 = deepcopy(sender)
    recipient2 = deepcopy(recipient1)
    test_case2 = deepcopy(test_case)

    inputs = []
    for i, outpoint in enumerate(outpoints):
        inputs += [{
            'prevout': list(outpoint) + [get_p2pkh_scriptsig(input_pub_keys[i], input_priv_keys[i][0]), ""],
            'scriptPubKey': get_p2pkh_scriptPubKey(input_pub_keys[i]),
        }]

    sender1['given']['inputs'] = sender['given']['inputs'] = add_private_keys(deepcopy(inputs), input_priv_keys)
    sender['given']['recipients'] = addresses1
    recipient1['given']['inputs'] = inputs
    recipient2['given']['inputs'] = inputs
    recipient1['given']['key_material']['scan_priv_key'] = scan1.get_bytes().hex()
    recipient1['given']['key_material']['spend_priv_key'] = spend1.get_bytes().hex()
    recipient1['expected']['addresses'] = [address1]
    recipient2['given']['key_material']['scan_priv_key'] = scan2.get_bytes().hex()
    recipient2['given']['key_material']['spend_priv_key'] = spend2.get_bytes().hex()
    recipient2['expected']['addresses'] = [address2]

    outpoints_hash = reference.hash_outpoints(outpoints)
    outputs = reference.create_outputs(input_priv_keys, outpoints_hash, addresses1, hrp=HRP)
    sender['expected']['outputs'] = outputs
    output_pub_keys = [recipient[0] for recipient in outputs]
    recipient1['given']['outputs'] = output_pub_keys

    A_sum = sum(input_pub_keys)
    add_to_wallet = reference.scanning(
        scan1,
        Spend1,
        A_sum,
        reference.hash_outpoints(outpoints),
        [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
    )
    for o in add_to_wallet:

        pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
        full_private_key = spend1.add(
            bytes.fromhex(o['priv_key_tweak'])
        )
        if full_private_key.get_pubkey().get_y()%2 != 0:
            full_private_key.negate()

        sig = full_private_key.sign_schnorr(msg, aux)
        assert pubkey.verify_schnorr(sig, msg)
        o['signature'] = sig.hex()

    recipient1['expected']['outputs'] = add_to_wallet
    test_case['sending'].extend([sender])
    test_case['receiving'].extend([recipient1])
    test_case["comment"] = "Multiple outputs: multiple outputs, same recipient"
    test_cases.append(test_case)

    sender1['given']['recipients'] = addresses1 + addresses2
    outputs = reference.create_outputs(input_priv_keys, outpoints_hash, addresses1 + addresses2, hrp=HRP)
    sender1['expected']['outputs'] = outputs
    output_pub_keys = [recipient[0] for recipient in outputs]
    recipient1['given']['outputs'] = output_pub_keys
    recipient2['given']['outputs'] = output_pub_keys

    add_to_wallet = reference.scanning(
        scan2,
        Spend2,
        A_sum,
        reference.hash_outpoints(outpoints),
        [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
    )
    for o in add_to_wallet:

        pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
        full_private_key = spend2.add(
            bytes.fromhex(o['priv_key_tweak'])
        )
        if full_private_key.get_pubkey().get_y()%2 != 0:
            full_private_key.negate()

        sig = full_private_key.sign_schnorr(msg, aux)
        assert pubkey.verify_schnorr(sig, msg)
        o['signature'] = sig.hex()

    recipient2['expected']['outputs'] = add_to_wallet
    test_case2['sending'].extend([sender1])
    test_case2['receiving'].extend([recipient1, recipient2])
    test_case2["comment"] = "Multiple outputs: multiple outputs, multiple recipients"
    test_cases.append(test_case2)

    return test_cases


# In[13]:


def generate_paying_to_self_test():

    msg = reference.sha256(b'message')
    aux = reference.sha256(b'random auxiliary data')
    outpoints = [
        ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0),
        ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0)
    ]

    sender_bip32_seed = 'deadbeef'
    recipient_bip32_seed = 'deadbeef'
    i1, I1 = get_key_pair(0, seed=bytes.fromhex(sender_bip32_seed))
    i2, I2 = get_key_pair(1)
    input_priv_keys = [(i1, False), (i2, False)]
    input_pub_keys = [I1, I2]

    sender, recipient, test_case = new_test_case()
    sender['given']['outpoints'] = outpoints
    recipient['given']['outpoints'] = outpoints
    sender['given']['input_priv_keys'].extend([i1.get_bytes().hex(), i2.get_bytes().hex()])
    recipient['given']['input_pub_keys'].extend([I1.get_bytes(False).hex(), I2.get_bytes(False).hex()])

    b_scan, b_spend, B_scan, B_spend = create_silent_payment_key_pair(bytes.fromhex(recipient_bip32_seed))
    recipient['given']['bip32_seed'] = recipient_bip32_seed
    recipient['given']['scan_priv_key'] = b_scan.get_bytes().hex()
    recipient['given']['spend_priv_key'] = b_spend.get_bytes().hex()
    address = reference.encode_silent_payment_address(B_scan, B_spend, hrp=HRP)

    sender['given']['recipients'].extend([(address, 1.0)])
    recipient['expected']['addresses'].extend([address])

    outpoints_hash = reference.hash_outpoints(outpoints)
    outputs = reference.create_outputs(input_priv_keys, outpoints_hash, [(address, 1.0)], hrp=HRP)
    sender['expected']['outputs'] = outputs
    output_pub_keys = [recipient[0] for recipient in outputs]
    recipient['given']['outputs'] = output_pub_keys

    A_sum = sum(input_pub_keys)
    add_to_wallet = reference.scanning(
        b_scan,
        B_spend,
        A_sum,
        reference.hash_outpoints(outpoints),
        [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
    )
    for o in add_to_wallet:

        pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
        full_private_key = b_spend.add(
            bytes.fromhex(o['priv_key_tweak'])
        )
        if full_private_key.get_pubkey().get_y()%2 != 0:
            full_private_key.negate()

        sig = full_private_key.sign_schnorr(msg, aux)
        assert pubkey.verify_schnorr(sig, msg)
        o['signature'] = sig.hex()

    recipient['expected']['outputs'] = add_to_wallet
    test_case['sending'].extend([sender])
    test_case['receiving'].extend([recipient])

    return test_case


def generate_multiple_outputs_with_labels_tests():

    msg = reference.sha256(b'message')
    aux = reference.sha256(b'random auxiliary data')
    G = ECKey().set(1).get_pubkey()
    recipient_test_cases = []
    outpoints = [
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0),
    ]
    sender_bip32_seed = 'deadbeef'
    i1, I1 = get_key_pair(0, seed=bytes.fromhex(sender_bip32_seed))
    i2, I2 = get_key_pair(1, seed=bytes.fromhex(sender_bip32_seed))
    input_priv_keys = [(i1, False), (i2, False)]
    input_pub_keys = [I1, I2]

    recipient_bip32_seed = 'f00dbabe'
    scan1, spend1, Scan1, Spend1 = reference.derive_silent_payment_key_pair(bytes.fromhex(recipient_bip32_seed))
    address = reference.encode_silent_payment_address(Scan1, Spend1, hrp=HRP)
    label_address_one = reference.create_labeled_silent_payment_address(Scan1, Spend1, m=(1).to_bytes(32, 'big'), hrp=HRP)
    label_address_two = reference.create_labeled_silent_payment_address(Scan1, Spend1, m=(1337).to_bytes(32,'big'), hrp=HRP)
    labels_one = [[((1).to_bytes(32, 'big')*G).get_bytes(False).hex(), (1).to_bytes(32, 'big').hex()]]
    labels_three = [[(1*G).get_bytes(False).hex(), (1).to_bytes(32, 'big').hex()], [(1337*G).get_bytes(False).hex(), (1337).to_bytes(32, 'big').hex()]]
    addresses1 = [(address, 1.0), (label_address_one, 2.0)]
    addresses2 = [(label_address_one, 3.0), (label_address_one, 4.0)]
    addresses3 = [(address, 5.0), (label_address_one, 6.0), (label_address_two, 7.0), (label_address_two, 8.0)]

    test_cases = []
    labels = [labels_one, labels_one, labels_three]
    sp_addresses = [[address, label_address_one], [address, label_address_one], [address, label_address_one, label_address_two]]
    comments = [
        "Multiple outputs with labels: un-labeled and labeled address; same recipient",
        "Multiple outputs with labels: multiple outputs for labeled address; same recipient",
        "Multiple outputs with labels: un-labeled, labeled, and multiple outputs for labeled address; multiple recipients",
    ]
    for i, addrs in enumerate([addresses1, addresses2, addresses3]):
        sender, recipient, test_case = new_test_case()

        inputs = []
        for i, outpoint in enumerate(outpoints):
            inputs += [{
                'prevout': list(outpoint) + [get_p2pkh_scriptsig(input_pub_keys[i], input_priv_keys[i][0]), ""],
                'scriptPubKey': get_p2pkh_scriptPubKey(input_pub_keys[i]),
            }]

        sender['given']['inputs'] = add_private_keys(deepcopy(inputs), input_priv_keys)
        recipient['given']['inputs'] = inputs

        recipient['given']['key_material']['scan_priv_key'] = scan1.get_bytes().hex()
        recipient['given']['key_material']['spend_priv_key'] = spend1.get_bytes().hex()
        sender['given']['recipients'] = addrs
        recipient['expected']['addresses'] = sp_addresses[i]
        recipient['given']['labels'] = labels[i]
        outpoints_hash = reference.hash_outpoints(outpoints)
        outputs = reference.create_outputs(input_priv_keys, outpoints_hash, addrs, hrp=HRP)
        sender['expected']['outputs'] = outputs
        output_pub_keys = [recipient[0] for recipient in outputs]
        recipient['given']['outputs'] = output_pub_keys

        A_sum = sum(input_pub_keys)
        add_to_wallet = reference.scanning(
            scan1,
            Spend1,
            A_sum,
            reference.hash_outpoints(outpoints),
            [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
            labels={l[0]:l[1] for l in labels[i]},
        )
        for o in add_to_wallet:

            pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
            full_private_key = spend1.add(
                bytes.fromhex(o['priv_key_tweak'])
            )
            if full_private_key.get_pubkey().get_y()%2 != 0:
                full_private_key.negate()

            sig = full_private_key.sign_schnorr(msg, aux)
            assert pubkey.verify_schnorr(sig, msg)
            o['signature'] = sig.hex()

        recipient['expected']['outputs'] = add_to_wallet
        test_case['sending'].extend([sender])
        test_case['receiving'].extend([recipient])
        test_case["comment"] = comments[i]
        test_cases.append(test_case)

    return test_cases


def generate_single_output_input_tests():

    msg = reference.sha256(b'message')
    aux = reference.sha256(b'random auxiliary data')
    G = ECKey().set(1).get_pubkey()
    outpoints = [
        ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0),
        ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0)
    ]

    sender_bip32_seed = 'deadbeef'
    recipient_bip32_seed = 'f00dbabe'
    i1, I1 = get_key_pair(0, seed=bytes.fromhex(sender_bip32_seed))
    i2, I2 = get_key_pair(1, seed=bytes.fromhex(sender_bip32_seed))
    i3, I3 = get_key_pair(2, seed=bytes.fromhex(sender_bip32_seed))
    i4, I4 = get_key_pair(3, seed=bytes.fromhex(sender_bip32_seed))

    if I1.get_y()%2 != 0:
        i1.negate()
        I1.negate()

    if I2.get_y()%2 != 0:
        i2.negate()
        I2.negate()

    if I3.get_y()%2 == 0:
        i3.negate()
        I3.negate()

    if I4.get_y()%2 == 0:
        i4.negate()
        I4.negate()


    address_reuse = [
        [(i1, False), (i1, False)],
        [I1, I1]
    ]
    taproot_only = [
        [(i1, True), (i2, True)],
        [I1, I2]
    ]

    taproot_only_with_odd_y = [
        [(i1, True), (i4, True)],
        [I1, I4]
    ]
    mixed = [
        [(i1, True), (i3, False)],
        [I1, I3]
    ]
    mixed_with_odd_y = [
        [(i4, True), (i3, False)],
        [I4, I3]
    ]
    test_cases = []
    comments = [
        "Single recipient: multiple UTXOs from the same public key",
        "Single recipient: taproot only inputs with even y-values",
        "Single recipient: taproot only with mixed even/odd y-values",
        "Single recipient: taproot input with even y-value and non-taproot input",
        "Single recipient: taproot input with odd y-value and non-taproot input"
    ]
    for i, inputs in enumerate([address_reuse, taproot_only, taproot_only_with_odd_y, mixed, mixed_with_odd_y]):
        sender, recipient, test_case = new_test_case()

        inp = []
        for x, (key, is_taproot) in enumerate(inputs[0]):
            pub_key = inputs[1][x]
            if is_taproot:
                inp += [{
                    "prevout": list(outpoints[x]) + ["", get_p2tr_witness(key)],
                    "scriptPubKey": get_p2tr_scriptPubKey(pub_key)
                }]
            else:
                inp += [{
                    "prevout": list(outpoints[x]) + [get_p2pkh_scriptsig(pub_key, key), ""],
                    "scriptPubKey": get_p2pkh_scriptPubKey(pub_key)
                }]

        priv_keys = []
        for (priv_key, is_taproot) in inputs[0]:
            priv_keys += [priv_key.get_bytes().hex()]
            

        sender['given']['inputs'] = add_private_keys(deepcopy(inp), inputs[0])
        recipient['given']['inputs'] = inp

        b_scan, b_spend, B_scan, B_spend = reference.derive_silent_payment_key_pair(bytes.fromhex(recipient_bip32_seed))
        recipient['given']['key_material']['scan_priv_key'] = b_scan.get_bytes().hex()
        recipient['given']['key_material']['spend_priv_key'] = b_spend.get_bytes().hex()
        address = reference.encode_silent_payment_address(B_scan, B_spend, hrp=HRP)

        sender['given']['recipients'].extend([(address, 1.0)])
        recipient['expected']['addresses'].extend([address])

        outpoints_hash = reference.hash_outpoints(outpoints)
        outputs = reference.create_outputs(inputs[0], outpoints_hash, [(address, 1.0)], hrp=HRP)
        sender['expected']['outputs'] = outputs
        output_pub_keys = [recipient[0] for recipient in outputs]
        recipient['given']['outputs'] = output_pub_keys

        A_sum = sum([p if not inputs[0][i][1] or p.get_y()%2==0 else p * -1  for i, p in enumerate(inputs[1])])
        add_to_wallet = reference.scanning(
            b_scan,
            B_spend,
            A_sum,
            reference.hash_outpoints(outpoints),
            [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
        )
        for o in add_to_wallet:

            pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
            full_private_key = b_spend.add(
                bytes.fromhex(o['priv_key_tweak'])
            )
            if full_private_key.get_pubkey().get_y()%2 != 0:
                full_private_key.negate()

            sig = full_private_key.sign_schnorr(msg, aux)
            assert pubkey.verify_schnorr(sig, msg)
            o['signature'] = sig.hex()

        recipient['expected']['outputs'] = add_to_wallet
        test_case['sending'].extend([sender])
        test_case['receiving'].extend([recipient])
        test_case["comment"] = comments[i]
        test_cases.append(test_case)

    return test_cases


def generate_change_tests():

    sender, recipient, test_case = new_test_case()

    msg = reference.sha256(b'message')
    aux = reference.sha256(b'random auxiliary data')
    G = ECKey().set(1).get_pubkey()
    recipient_test_cases = []
    outpoints = [
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0),
    ]
    sender_bip32_seed = 'deadbeef'
    i1, I1 = get_key_pair(0, seed=bytes.fromhex(sender_bip32_seed))
    i2, I2 = get_key_pair(1, seed=bytes.fromhex(sender_bip32_seed))
    input_priv_keys = [(i1, False), (i2, False)]
    input_pub_keys = [I1, I2]

    scan0, spend0, Scan0, Spend0 = reference.derive_silent_payment_key_pair(bytes.fromhex(sender_bip32_seed))
    sender_address = reference.encode_silent_payment_address(Scan0, Spend0, hrp=HRP)
    change_label = reference.sha256(scan0.get_bytes())
    change_labels = [[(change_label*G).get_bytes(False).hex(), change_label.hex()]]
    change_address = reference.create_labeled_silent_payment_address(Scan0, Spend0, m=change_label, hrp=HRP)

    recipient_bip32_seed = 'f00dbabe'
    seeds = [sender_bip32_seed, recipient_bip32_seed]
    scan1, spend1, Scan1, Spend1 = reference.derive_silent_payment_key_pair(bytes.fromhex(recipient_bip32_seed))
    address = reference.encode_silent_payment_address(Scan1, Spend1, hrp=HRP)
    addresses = [(address, 1.0), (change_address, 2.0)]

    test_cases = []
    sp_recipients = [[address, change_address]]

    rec1, rec2 = deepcopy(recipient), deepcopy(recipient)
    rec1['given']['key_material']['scan_priv_key'] = scan0.get_bytes().hex()
    rec1['given']['key_material']['spend_priv_key'] = spend0.get_bytes().hex()
    rec2['given']['key_material']['scan_priv_key'] = scan1.get_bytes().hex()
    rec2['given']['key_material']['spend_priv_key'] = spend1.get_bytes().hex()
    rec1['expected']['addresses'] = [sender_address, change_address]
    rec1['given']['labels'] = change_labels
    rec2['expected']['addresses'] = [address]


    inputs = []
    for i, outpoint in enumerate(outpoints):
        inputs += [{
            'prevout': list(outpoint) + [get_p2pkh_scriptsig(input_pub_keys[i], input_priv_keys[i][0]), ""],
            'scriptPubKey': get_p2pkh_scriptPubKey(input_pub_keys[i]),
        }]

    sender['given']['inputs'] = add_private_keys(deepcopy(inputs), input_priv_keys)
    sender['given']['recipients'] = addresses
    outputs = reference.create_outputs(input_priv_keys, reference.hash_outpoints(outpoints), addresses, hrp=HRP)
    sender['expected']['outputs'] = outputs

    output_pub_keys = [recipient[0] for recipient in outputs]

    test_case['sending'].extend([sender])
    labels = [change_labels, []]
    for i, rec in enumerate([rec1, rec2]):
        rec['given']['inputs'] = inputs
        rec['given']['outputs'] = output_pub_keys

        A_sum = sum(input_pub_keys)
        scan, spend, Scan, Spend = reference.derive_silent_payment_key_pair(bytes.fromhex(seeds[i]))
        add_to_wallet = reference.scanning(
            scan,
            Spend,
            A_sum,
            reference.hash_outpoints(outpoints),
            [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
            labels={l[0]:l[1] for l in labels[i]},
        )
        for o in add_to_wallet:

            pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
            full_private_key = spend.add(
                bytes.fromhex(o['priv_key_tweak'])
            )
            if full_private_key.get_pubkey().get_y()%2 != 0:
                full_private_key.negate()

            sig = full_private_key.sign_schnorr(msg, aux)
            assert pubkey.verify_schnorr(sig, msg)
            o['signature'] = sig.hex()

        rec['expected']['outputs'] = add_to_wallet
        test_case['receiving'].extend([rec])
    test_case["comment"] = "Single recipient: use silent payments for sender change"
    test_cases.append(test_case)
    return test_cases


# In[17]:

def generate_all_inputs_test():

    sender, recipient, test_case = new_test_case()

    msg = reference.sha256(b'message')
    aux = reference.sha256(b'random auxiliary data')
    recipient_test_cases = []
    outpoints = [
            ("f4184fc596403b9d638783cf57adfe4c75c605f6356fbc91338530e9831e9e16", 0),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 0),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 1),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 2),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 3),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 4),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 5),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 6),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 7),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 8),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 9),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 10),
            ("a1075db55d416d3ca199f55b6084e2115b9345e16c5cf302fc80e9d5fbf5d48d", 11),
    ]
    sender_bip32_seed = 'deadbeef'
    input_priv_keys = []
    input_pub_keys = []

    recipient_bip32_seed = 'f00dbabe'
    scan, spend, Scan, Spend = reference.derive_silent_payment_key_pair(bytes.fromhex(recipient_bip32_seed))
    address = reference.encode_silent_payment_address(Scan, Spend, hrp=HRP)
    addresses = [(address, 1.0)]

    recipient['given']['key_material']['scan_priv_key'] = scan.get_bytes().hex()
    recipient['given']['key_material']['spend_priv_key'] = spend.get_bytes().hex()
    recipient['expected']['addresses'] = [address]

    inputs = []

    ## included
    # p2pk
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    sig = priv.sign_ecdsa(msg, False).hex()
    x = len(sig) // 2
    inputs += [{
        'prevout': list(outpoints[i]) + [f'{x:0x}' + sig, ""],
        'scriptPubKey': "21" + pub.get_bytes(False).hex() + "ac",
    }]
    input_priv_keys += [(priv, False)]
    input_pub_keys += [pub]

    # p2pkh
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    inputs += [{
        'prevout': list(outpoints[i]) + [get_p2pkh_scriptsig(pub, priv), ""],
        'scriptPubKey': get_p2pkh_scriptPubKey(pub),
    }]
    input_priv_keys += [(priv, False)]
    input_pub_keys += [pub]

    # p2pkh maleated
    # TODO: make dummy look like public key, wrap in OP_IF <real_script> <fake_key> 
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    inputs += [{
        'prevout': list(outpoints[i]) + ["0075" + get_p2pkh_scriptsig(pub, priv), ""],
        'scriptPubKey': get_p2pkh_scriptPubKey(pub),
    }]
    input_priv_keys += [(priv, False)]
    input_pub_keys += [pub]

    # p2pkh hybrid key
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    inputs += [{
        'prevout': list(outpoints[i]) + [get_p2pkh_scriptsig(pub, priv, hybrid=True), ""],
        'scriptPubKey': get_p2pkh_scriptPubKey(pub, hybrid=True),
    }]
    input_priv_keys += [(priv, False)]
    input_pub_keys += [pub]

    # p2wpkh
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    sig = priv.sign_ecdsa(msg, False).hex()
    inputs += [{
        'prevout': list(outpoints[i]) + ["", serialize_witness_stack([sig, pub.get_bytes(False).hex()])],
        'scriptPubKey': "0014" + rmd160(pub.get_bytes(False)),
    }]
    input_priv_keys += [(priv, False)]
    input_pub_keys += [pub]

    # p2wpkh hybrid key
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    sig = priv.sign_ecdsa(msg, False).hex()
    inputs += [{
        'prevout': list(outpoints[i]) + ["", serialize_witness_stack([sig, encode_hybrid_key(pub).hex()])],
        'scriptPubKey': "0014" + rmd160(encode_hybrid_key(pub)),
    }]
    input_priv_keys += [(priv, False)]
    input_pub_keys += [pub]

    # p2sh-p2wpkh
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    sig = priv.sign_ecdsa(msg, False).hex()
    witnessProgramm = bytes([0x00, 0x14]) + bytes.fromhex(rmd160(pub.get_bytes(False)))
    inputs += [{
        'prevout': list(outpoints[i]) + [
            # scriptSig
            "16" + witnessProgramm.hex(),
            # witness
            serialize_witness_stack([sig, pub.get_bytes(False).hex()])
        ],
        'scriptPubKey': "a914" + rmd160(witnessProgramm) + "87",
    }]
    input_priv_keys += [(priv, False)]
    input_pub_keys += [pub]

    # p2tr key path
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    inputs += [{
        'prevout': list(outpoints[i]) + ["", get_p2tr_witness(priv)],
        'scriptPubKey': get_p2tr_scriptPubKey(pub),
    }]
    input_priv_keys += [(priv, True)]
    input_pub_keys += [pub]

    # p2tr script path
    i = len(inputs)
    priv_key, pub_key = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    # can verify calculation below with following command
    # tap ae0554b17264a231ec94407263897a6294a92f8f1f587e56c1d4e9a1bad0d571 1 '[OP_TRUE]' 0
    leaf_version = "c0"
    script = "51" # OP_TRUE
    if pub_key.get_y() % 2 != 0:
        priv_key.negate()
    leaf_hash = TaggedHash("TapLeaf", bytes.fromhex(leaf_version + "01" + script))
    tap_tweak = TaggedHash("TapTweak", pub_key.get_bytes() + leaf_hash)
    tweaked_key = pub_key.tweak_add(tap_tweak)
    control_block = leaf_version + pub_key.get_bytes().hex()
    inputs += [{
        'prevout': list(outpoints[i]) + ["", serialize_witness_stack([script, control_block])],
        'scriptPubKey': get_p2tr_scriptPubKey(tweaked_key),
    }]
    input_pub_keys += [tweaked_key]
    input_priv_keys += [(priv_key.tweak_add(tap_tweak), True)]
    eligible = i

    ## exlcuded
    # p2tr spend path with P == H
    i = len(inputs)
    priv_key, _ = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    G2 = bytes([0x04]) + SECP256K1_G[0].to_bytes(32, 'big') + SECP256K1_G[1].to_bytes(32, 'big')
    pub_key = ECPubKey().set(reference.sha256(G2))
    # can verify calculation below with following command
    # tap 50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee9ace803ac0 1 '[OP_TRUE]' 0
    # it's intended that the keys don't much
    leaf_hash = TaggedHash("TapLeaf", bytes.fromhex(leaf_version + "01" + script))
    tap_tweak = TaggedHash("TapTweak", pub_key.get_bytes() + leaf_hash)
    tweaked_key = pub_key.tweak_add(tap_tweak)
    leaf_version = "c1" # the final tweaked key key is not even
    control_block = leaf_version + pub_key.get_bytes().hex()
    inputs += [{
        'prevout': list(outpoints[i]) + ["", serialize_witness_stack([script, control_block])],
        'scriptPubKey': get_p2tr_scriptPubKey(tweaked_key),
    }]
    input_pub_keys += [tweaked_key]
    input_priv_keys += [(priv_key.tweak_add(tap_tweak), True)]

    ## p2sh
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    # use standard p2pkh within p2sh
    redeem_script = get_p2pkh_scriptPubKey(pub)
    s = len(redeem_script) // 2
    ser_script = f'{s:0x}' + redeem_script
    inputs += [{
        'prevout': list(outpoints[i]) + [get_p2pkh_scriptsig(pub, priv) + ser_script, ""],
        'scriptPubKey': "a914" + rmd160(bytes.fromhex(redeem_script)) + "87",
    }]
    input_pub_keys += [pub]
    input_priv_keys += [(priv, False)]
    # TODO: broken p2sh

    ## p2wsh
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    # use standard p2pkh within p2wsh
    redeem_script = get_p2pkh_scriptPubKey(pub)
    msg = reference.sha256(b'message')
    sig = priv_key.sign_ecdsa(msg, False).hex()
    inputs += [{
        'prevout': list(outpoints[i]) + ["", serialize_witness_stack([sig, pub.get_bytes(False).hex(), redeem_script])],
        'scriptPubKey': "0020" + reference.sha256(bytes.fromhex(redeem_script)).hex(),
    }]
    input_pub_keys += [pub]
    input_priv_keys += [(priv, False)]

    # p2sh-p2wsh
    i = len(inputs)
    priv, pub = get_key_pair(i, seed=bytes.fromhex(sender_bip32_seed))
    # use standard p2pkh script
    redeem_script = get_p2pkh_scriptPubKey(pub)
    witness_program = bytes([0x00, 0x20]) + reference.sha256(bytes.fromhex(redeem_script))
    msg = reference.sha256(b'message')
    sig = priv_key.sign_ecdsa(msg, False).hex()
    inputs += [{
        'prevout': list(outpoints[i]) + [
            # scriptSig
            "22" + witness_program.hex(),
            # witness
            serialize_witness_stack([sig, pub.get_bytes(False).hex(), redeem_script])
        ],
        'scriptPubKey': "a914" + rmd160(witness_program) + "87",
    }]
    input_pub_keys += [pub]
    input_priv_keys += [(priv, False)]

    ## p2ms
    #i = len(inputs)
    #inputs += [{
    #    'prevout': list(outpoints[i]) + [get_p2pkh_scriptsig(input_pub_keys[i], input_priv_keys[i][0]), ""],
    #    'scriptPubKey': get_p2pkh_scriptPubKey(input_pub_keys[i]),
    #}]
    # TODO: add non-standard spend
    # TODO: unkown witness 


    sender['given']['recipients'] = addresses
    outputs = reference.create_outputs(input_priv_keys[:eligible+1], reference.hash_outpoints(outpoints), addresses, hrp=HRP)
    sender['expected']['outputs'] = outputs
    sender['given']['inputs'] = add_private_keys(deepcopy(inputs), input_priv_keys)

    output_pub_keys = [recipient[0] for recipient in outputs]

    test_case['sending'].extend([sender])
    recipient['given']['inputs'] = inputs
    recipient['given']['outputs'] = output_pub_keys

    A_sum = sum([p if not input_priv_keys[i][1] or p.get_y()%2==0 else p * -1  for i, p in enumerate(input_pub_keys[:eligible+1])])
    add_to_wallet = reference.scanning(
        scan,
        Spend,
        A_sum,
        reference.hash_outpoints(outpoints),
        [ECPubKey().set(bytes.fromhex(pub)) for pub in output_pub_keys],
        labels={},
    )
    for o in add_to_wallet:

        pubkey = ECPubKey().set(bytes.fromhex(o['pub_key']))
        full_private_key = spend.add(
            bytes.fromhex(o['priv_key_tweak'])
        )
        if full_private_key.get_pubkey().get_y()%2 != 0:
            full_private_key.negate()

        sig = full_private_key.sign_schnorr(msg, aux)
        assert pubkey.verify_schnorr(sig, msg)
        o['signature'] = sig.hex()

    recipient['expected']['outputs'] = add_to_wallet
    test_case['receiving'].extend([recipient])
    test_case["comment"] = "Pubkey extraction"
    test_cases = []
    test_cases.append(test_case)
    return test_cases

with open("send_and_receive_test_vectors.json", "w") as f:
    json.dump(
        generate_single_output_outpoint_tests() +
        generate_single_output_input_tests() +
        generate_multiple_output_tests() +
        generate_labeled_output_tests() +
        generate_multiple_outputs_with_labels_tests() +
        generate_change_tests() +
        generate_all_inputs_test(),
        f,
        indent=4,
    )
