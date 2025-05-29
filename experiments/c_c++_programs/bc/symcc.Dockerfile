# Use the final stage from SymCC
FROM symcc AS bc

USER root

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get install -y \
    texinfo yacc && \
    rm -rf /var/lib/apt/lists/*


# -------------------------------------------------------------
# Download and extract bc
# -------------------------------------------------------------
WORKDIR /
RUN wget https://ftp.gnu.org/gnu/bc/bc-1.08.1.tar.gz
RUN tar -xzf bc-1.08.1.tar.gz

RUN cp -r bc-1.08.1 /bc-gcov && cp -r bc-1.08.1 /bc-symcc


# -------------------------------------------------------------
# Build bc with SymCC
# -------------------------------------------------------------
WORKDIR /bc-symcc
RUN CC=symcc CXX=sym++ ./configure
RUN CC=symcc CXX=sym++ make


# -------------------------------------------------------------
# Build bc with GCOV
# -------------------------------------------------------------
WORKDIR /bc-gcov
RUN CC=gcc CXX=g++ ./configure
RUN CC=gcc CXX=g++ make AM_CFLAGS="-fprofile-arcs -ftest-coverage"


# -------------------------------------------------------------
# Prepare testing directory
# -------------------------------------------------------------

COPY ./seeds /seeds
COPY ./run.sh /run.sh
COPY ./coverage.sh /coverage.sh

CMD ["/bin/bash"]
