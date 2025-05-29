# Use the final stage from SymCC
FROM concolic AS bc



USER root

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    texinfo && \
    rm -rf /var/lib/apt/lists/*


# -------------------------------------------------------------
# Download and extract bc
# -------------------------------------------------------------
WORKDIR /
RUN wget https://ftp.gnu.org/gnu/bc/bc-1.08.1.tar.gz
RUN tar -xzf bc-1.08.1.tar.gz

RUN mv bc-1.08.1 /bc-gcov

COPY ./bc-1.08.1-instr.tar.gz ./bc-1.08.1-instr.tar.gz
RUN tar -xzf bc-1.08.1-instr.tar.gz && mv bc-1.08.1-instr /bc-instr


# -------------------------------------------------------------
# Build bc with GCOV
# -------------------------------------------------------------
WORKDIR /bc-gcov
RUN CC=gcc CXX=g++ ./configure
RUN CC=gcc CXX=g++ make AM_CFLAGS="-fprofile-arcs -ftest-coverage"

# -------------------------------------------------------------
# Build bc with instrumentation
# -------------------------------------------------------------

WORKDIR /bc-instr
RUN CC=gcc CXX=g++ ./configure
RUN CC=gcc CXX=g++ make


#  -------------------------------------------------------------
# Build bc with Sanitizer
# -------------------------------------------------------------


# -------------------------------------------------------------
# Prepare testing directory
# -------------------------------------------------------------

COPY ./seed_execs /seed_execs
COPY ./run.sh /run.sh
COPY ./coverage.sh /coverage.sh

CMD ["/bin/bash"]
