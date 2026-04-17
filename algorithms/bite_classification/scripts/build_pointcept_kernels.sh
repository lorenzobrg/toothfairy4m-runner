#!/usr/bin/env bash
set -euo pipefail

: "${TORCH_CUDA_ARCH_LIST:=7.5}"
export TORCH_CUDA_ARCH_LIST

echo "Building Pointcept kernels with TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}"

pip install --no-cache-dir --no-build-isolation /opt/Bits2Bites/libs/pointops -v
pip install --no-cache-dir --no-build-isolation /opt/Bits2Bites/libs/pointgroup_ops -v
