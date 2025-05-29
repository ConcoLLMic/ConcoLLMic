FROM klee
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /
RUN wget https://ftp.gnu.org/gnu/bc/bc-1.08.1.tar.gz
RUN tar -xzf bc-1.08.1.tar.gz

RUN cp -r bc-1.08.1 /bc-gcov && cp -r bc-1.08.1 /bc-klee

WORKDIR /bc-gcov
RUN CC=gcc CXX=g++ ./configure
RUN CC=gcc CXX=g++ make AM_CFLAGS="-fprofile-arcs -ftest-coverage"

WORKDIR /bc-klee
RUN CC="wllvm" CXX="wllvm++" ./configure --disable-nls CFLAGS="-g -O1 -Xclang -disable-llvm-passes -D__NO_STRING_INLINES -D_FORTIFY_SOURCE=0 -U__OPTIMIZE__"
RUN CC="wllvm" CXX="wllvm++" make
RUN extract-bc bc/bc

COPY ./seeds_klee /seeds
COPY ./run.sh /run.sh
COPY ./coverage.sh /coverage.sh

RUN chmod +x /run.sh
RUN chmod +x /coverage.sh

CMD ["/bin/bash"]