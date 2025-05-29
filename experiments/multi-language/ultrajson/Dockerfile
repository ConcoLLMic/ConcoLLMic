FROM concolic

USER root

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    make \
    openjdk-8-jdk \
    maven \
    vim \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------------------------------------
# Install dependencies
# -------------------------------------------------------------

RUN pip3 install --upgrade setuptools>=61.0.0 
RUN pip3 install coverage gcovr setuptools-scm==6.4.2


# -------------------------------------------------------------
# Download ultrajson
# -------------------------------------------------------------
WORKDIR /
RUN git clone https://github.com/ultrajson/ultrajson.git /ultrajson && cd /ultrajson && git reset --hard 2ea54f6a1d1b8e2bc3a27c491a63238cf244f087
# copy driver
COPY ./ujson_app.py /ultrajson/ujson_app.py  
RUN cp -r /ultrajson /ultrajson_asan && mv /ultrajson /ultrajson_cov

COPY ./ultrajson_instr.tar.gz /
RUN tar -xzf ultrajson_instr.tar.gz


# -------------------------------------------------------------
# Build ultrajson with coverage
# -------------------------------------------------------------
WORKDIR /ultrajson_cov
RUN CFLAGS="--coverage -O0" LDFLAGS="--coverage" python3 setup.py -q build_ext --inplace -f


# -------------------------------------------------------------
# Build ultrajson with Sanitizer
# -------------------------------------------------------------
WORKDIR /ultrajson_asan
RUN CC="clang -fsanitize=address,undefined -shared-libasan -fsanitize-undefined-trap-on-error -fno-sanitize-recover=all" \
    CXX="clang++ -fsanitize=address,undefined -shared-libasan -fsanitize-undefined-trap-on-error -fno-sanitize-recover=all" \
    LDSHARED="clang -shared -fsanitize=address,undefined -shared-libasan -fsanitize-undefined-trap-on-error -fno-sanitize-recover=all" \
    python3 setup.py build_ext --inplace -f


# -------------------------------------------------------------
# Build bc with instrumentation
# -------------------------------------------------------------

WORKDIR /ultrajson_instr
RUN git config --global --add safe.directory /ultrajson_instr
RUN python3 setup.py build_ext --inplace -f


# -------------------------------------------------------------
# Prepare testing directory
# -------------------------------------------------------------

COPY ./seed_execs /seed_execs
COPY ./run.sh /run.sh
COPY ./coverage.sh /coverage.sh

CMD ["/bin/bash"]