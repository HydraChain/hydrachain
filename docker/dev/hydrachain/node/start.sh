#!/bin/bash
set -e

# Wait for all nodes to come up
/root/settle_file.py /etc/hosts

cat /etc/hosts

SEED=${SEED:-23}
HOST_BASE_NAME=${HYDRACHAIN_HOST_PREFIX:-hydrachain}_node_
BOOTSTRAP_NODE_NAME=${HOST_BASE_NAME}bootstrap

if ! grep -q $BOOTSTRAP_NODE_NAME /etc/hosts ; then
    echo "No bootstrap node found. Aborting."
    exit 1
fi

OWN_IP=$(ip -o -4 addr show | awk -F '[ /]+' '/global/ {print $4}')
OWN_INDEX=$(egrep "$OWN_IP\s+${HOST_BASE_NAME}" /etc/hosts | grep -v bridge | sed -r "s/^.*${HOST_BASE_NAME}//")
OWN_NAME=${HOST_BASE_NAME}${OWN_INDEX}
NODE_COUNT=$(grep ${HOST_BASE_NAME} /etc/hosts | grep -v bridge | sed -r "s/^.*${HOST_BASE_NAME}//" | sort -n | tail -n1)
# Increment node count to account for bootstrap node
NODE_COUNT=$((NODE_COUNT+1))
BOOTSTRAP_NODE=$(/root/mk_enode.py --host ${BOOTSTRAP_NODE_NAME} ${SEED} 0)

if [ ${OWN_NAME} == ${BOOTSTRAP_NODE_NAME} ]; then
    OWN_INDEX=0
fi

(set -o posix; set)

cd /root/eth-net-intelligence-api
perl -pi -e "s/XXX/${OWN_NAME}/g" app.json
/usr/bin/pm2 start ./app.json

if [ -f /pyethapp.src/setup.py ]; then
    pip uninstall -y pyethapp

    rsync -a --delete /pyethapp.src/* /pyethapp/
    cd /pyethapp
    pip install -e .
fi

rsync -a --delete /hydrachain.src/* /hydrachain/
cd /hydrachain
pip install -e .

echo /usr/local/bin/hydrachain --bootstrap_node "$BOOTSTRAP_NODE" -l:debug -c jsonrpc.listen_host=0.0.0.0 "$@" runlocal --num_validators ${NODE_COUNT} --node_num ${OWN_INDEX} --seed ${SEED}
/usr/local/bin/hydrachain --bootstrap_node "$BOOTSTRAP_NODE" -l:debug -c jsonrpc.listen_host=0.0.0.0 "$@" runlocal --num_validators ${NODE_COUNT} --node_num ${OWN_INDEX} --seed ${SEED}
