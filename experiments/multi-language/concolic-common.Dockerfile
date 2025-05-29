FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    curl \
    git \
    autoconf \
    libtool \
    pkg-config \
    cmake \
    python3 \
    python3-pip \
    ca-certificates \
    lcov \
    clang-12 \
    clang++-12 \
    xxd \
    unzip \
    automake \
    build-essential \
    gcc \
    g++ \
    zlib1g \
    make


RUN ln -sf /usr/bin/clang-12 /usr/bin/clang
RUN ln -sf /usr/bin/clang++-12 /usr/bin/clang++
RUN pip3 install gcovr==6.0

RUN git clone https://github.com/ConcoLLMic/ConcoLLMic /concolic-agent

WORKDIR /concolic-agent

RUN pip install -r requirements.txt
RUN pip install -r requirements-dev.txt
