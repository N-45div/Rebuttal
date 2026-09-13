#!/usr/bin/env bash
# Proves Stripe test mode validates Visa CE3.0 rules: creates a fraud dispute,
# two prior undisputed charges, stages evidence (submit=false) and prints the
# eligibility status. Expected: requires_action -> qualified.
set -euo pipefail
S=${STRIPE_BIN:-stripe}
pi=$($S payment_intents create --amount=8900 --currency=usd --payment-method=pm_card_createCe3EligibleDispute --confirm=true --description="Order 1042 - trail shoes" -d "payment_method_types[]=card")
charge=$(echo "$pi" | grep '"latest_charge"' | sed 's/.*: "\(.*\)",/\1/')
sleep 2
du=$($S charges retrieve "$charge" | grep '"dispute"' | sed 's/.*: "\(.*\)",/\1/')
echo "dispute: $du"
echo "before:"; $S disputes retrieve "$du" | grep -A4 '"enhanced_eligibility"' | grep -E 'missing_|status'
p=()
for n in 0 1; do
  c=$($S payment_intents create --amount=4500 --currency=usd --payment-method=pm_card_visa --confirm=true --description="Order 09$n - prior order" -d "payment_method_types[]=card" | grep '"latest_charge"' | sed 's/.*: "\(.*\)",/\1/')
  P="evidence[enhanced_evidence][visa_compelling_evidence_3][prior_undisputed_transactions][$n]"
  p+=(-d "$P[charge]=$c" -d "$P[customer_email_address]=jordan@example.com" -d "$P[customer_account_id]=cust_7781" -d "$P[customer_purchase_ip]=146.196.38.93" -d "$P[product_description]=Order 09$n - prior order" -d "$P[shipping_address][line1]=12 Ridge Rd" -d "$P[shipping_address][city]=Boulder" -d "$P[shipping_address][state]=CO" -d "$P[shipping_address][postal_code]=80302" -d "$P[shipping_address][country]=US")
done
D="evidence[enhanced_evidence][visa_compelling_evidence_3][disputed_transaction]"
$S disputes update "$du" -d "submit=false" -d "$D[customer_email_address]=jordan@example.com" -d "$D[customer_account_id]=cust_7781" -d "$D[merchandise_or_services]=merchandise" -d "$D[shipping_address][line1]=12 Ridge Rd" -d "$D[shipping_address][city]=Boulder" -d "$D[shipping_address][state]=CO" -d "$D[shipping_address][postal_code]=80302" -d "$D[shipping_address][country]=US" "${p[@]}" > /dev/null
echo "after:"; $S disputes retrieve "$du" | grep -A4 '"enhanced_eligibility"' | grep -E 'missing_|status'
