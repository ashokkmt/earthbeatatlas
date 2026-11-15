#!/bin/sh
set -eu
envsubst < /etc/seaweedfs/s3.template.json > /tmp/seaweedfs-s3.json
exec weed server -dir=/data -ip=object-store -filer -s3 -s3.port=8333 \
  -s3.config=/tmp/seaweedfs-s3.json -volume.max=10
