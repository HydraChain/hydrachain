#!/bin/bash
set -e

SEED=23
# Wait for all nodes to come up
/root/settle_file.py /etc/hosts
HOST_BASE_NAME=hydrachain_node_

OWN_IP=$(ip -o -4 addr show | awk -F '[ /]+' '/global/ {print $4}')
OWN_INDEX=$(egrep "$OWN_IP\s+${HOST_BASE_NAME}" /etc/hosts | grep -v bridge | sed -r "s/^.*${HOST_BASE_NAME}//")
OWN_NAME=${HOST_BASE_NAME}${OWN_INDEX}
OWN_INDEX=$(($OWN_INDEX-1))
NODE_COUNT=$(grep ${HOST_BASE_NAME} /etc/hosts | grep -v bridge | sed -r "s/^.*${HOST_BASE_NAME}//" | sort -n | tail -n1)

BOOTSTRAP_NODE=$(/root/mk_enode.py --host ${HOST_BASE_NAME}${NODE_COUNT} ${SEED} ${NODE_COUNT})

cat /etc/hosts

cd /root/eth-net-intelligence-api
perl -pi -e "s/XXX/${OWN_NAME}/g" app.json
/usr/bin/pm2 start ./app.json

cp -a /hydrachain.src /hydrachain
cd /hydrachain
pip install -e .

echo /usr/local/bin/hydrachain --bootstrap_node "$BOOTSTRAP_NODE" runlocal --num_validators ${NODE_COUNT} --node_num ${OWN_INDEX} --seed ${SEED}
/usr/local/bin/hydrachain --bootstrap_node "$BOOTSTRAP_NODE" runlocal --num_validators ${NODE_COUNT} --node_num ${OWN_INDEX} --seed ${SEED}
