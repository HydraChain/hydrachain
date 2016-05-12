FROM python:2.7.10

RUN apt-get update &&\
    apt-get install -y curl git-core

RUN apt-get update &&\
    apt-get install -y build-essential libgmp-dev rsync

WORKDIR /
ADD . hydrachain

RUN pip install -U setuptools
# Pre-install hydrachain dependency
RUN pip install secp256k1==0.12.1

WORKDIR /hydrachain
# Reset potentially dirty directory and remove after install
RUN git reset --hard && pip install . && cd .. && rm -rf /hydrachain
WORKDIR /

ENTRYPOINT ["/usr/local/bin/hydrachain"]
CMD ["run"]
