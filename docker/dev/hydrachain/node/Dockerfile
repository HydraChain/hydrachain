FROM python:2.7.9

RUN apt-get update &&\
    apt-get install -y curl git-core &&\
    curl -sL https://deb.nodesource.com/setup | bash - &&\
    apt-get update &&\
    apt-get install -y nodejs


RUN apt-get update &&\
    apt-get install -y build-essential libgmp-dev rsync

RUN cd /root &&\
    git clone https://github.com/cubedro/eth-net-intelligence-api &&\
    cd eth-net-intelligence-api &&\
    npm install &&\
    npm install -g pm2


WORKDIR /
RUN git clone https://github.com/ethereum/pyrlp
WORKDIR /pyrlp
RUN pip install -e .

WORKDIR /
RUN git clone https://github.com/ethereum/pydevp2p
WORKDIR /pydevp2p
RUN pip install -e .

WORKDIR /
RUN git clone https://github.com/ethereum/pyethereum
WORKDIR /pyethereum
RUN pip install -e .

WORKDIR /
RUN git clone https://github.com/ethereum/pyethapp
WORKDIR /pyethapp
RUN pip install -e .


RUN pip install -U setuptools
RUN pip install ecdsa-recover


ADD start.sh /root/start.sh
ADD app.json /root/eth-net-intelligence-api/app.json
ADD mk_enode.py /root/mk_enode.py
ADD settle_file.py /root/settle_file.py

RUN chmod +x /root/start.sh
RUN chmod +x /root/mk_enode.py
RUN chmod +x /root/settle_file.py

ENTRYPOINT /root/start.sh
