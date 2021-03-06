import json
import os.path
import socket
import sys
import time

from bitcoin import SelectParams
import bitcoin.rpc
from bitcoin.core import *
import bitcoin.core.scripteval
import bitcoin.core.serialize

from cate import *
from cate.blockchain import *
from cate.error import ConfigurationError
from cate.fees import CFeeRate
from cate.tx import *

def spend_tx3(tx3_id, trade_id):
  print "Spending coins from trade " + trade_id
  audit = TradeDao(trade_id)

  offer = audit.load_json('2_offer.json')
  offer_currency_code = NETWORK_CODES[offer['offer_currency_hash']]
  private_key_a = audit.load_private_key('2_private_key.txt')
  secret = audit.load_secret('2_secret.txt')

  # Connect to the wallet
  bitcoin.SelectParams(config['daemons'][offer_currency_code]['network'], offer_currency_code)
  proxy = bitcoin.rpc.Proxy(service_port=config['daemons'][offer_currency_code]['port'], btc_conf_file=config['daemons'][offer_currency_code]['config'])
  fee_rate = CFeeRate(config['daemons'][offer_currency_code]['fee_per_kb'])

  # Monitor the block chain for TX3 being relayed
  statbuf = os.stat(audit.get_path('4_tx2.txt'))
  print "Waiting for TX " + b2lx(tx3_id) + " to confirm"
  tx3 = wait_for_tx_to_confirm(proxy, audit, tx3_id, statbuf.st_mtime)

  # TODO: Verify the secret we have matches the one expected; this is covered by
  # verify script later, but good to check here too

  # Get an address to pull the funds into
  own_address = proxy.getnewaddress("CATE " + trade_id)

  # Create a new transaction spending TX3, using the secret and our private key
  tx3_spend = build_tx1_tx3_spend(proxy, tx3, private_key_a, secret, own_address, fee_rate)

  # Send the transaction to the blockchain
  bitcoin.core.scripteval.VerifyScript(tx3_spend.vin[0].scriptSig, tx3.vout[0].scriptPubKey, tx3_spend, 0, (SCRIPT_VERIFY_P2SH,))
  try:
    proxy.sendrawtransaction(tx3_spend)
  except bitcoin.rpc.JSONRPCException as err:
    if err.error['code'] == -25:
      print "TX3 for trade " + trade_id + " has already been spent"
    else:
      raise err
  ready_transactions.pop(tx3_id, None)

  # Add a file to indicate the TX is complete
  audit.save_text('6_complete.txt', b2lx(tx3_spend.GetHash()))

# This is where both coins have been sent to the blockchains and 'A'
# can now use the secret to spend the coins sent by 'B'

try:
  config = load_configuration("config.yml")
except ConfigurationError as e:
  print e
  sys.exit(0)

# Scan the audit directory for transactions ready to spend
ready_transactions = {}
for trade_id in os.listdir('audits'):
  audit = TradeDao(trade_id)
  if not audit.file_exists('4_coins_sent.json'):
    continue
  if audit.file_exists('6_complete.txt'):
    continue
  confirmation = audit.load_json('4_confirmation.json')
  tx4 = CTransaction.deserialize(x(confirmation['tx4']))

  # Record a mapping from the TX3 ID to the trade ID
  ready_transactions[tx4.vin[0].prevout.hash] = trade_id

while ready_transactions:
  tx3ids = ready_transactions.keys()
  for tx3_id in tx3ids:
    trade_id = ready_transactions[tx3_id]
    spend_tx3(tx3_id, trade_id)
  if ready_transactions:
    time.sleep(5)
