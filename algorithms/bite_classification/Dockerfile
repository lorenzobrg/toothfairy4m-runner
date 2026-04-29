FROM pytorch/pytorch:2.5.0-cuda12.4-cudnn9-devel

ARG TORCH_CUDA_ARCH_LIST=7.5

WORKDIR /app

ENV TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST}
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/opt/Bits2Bites:${PYTHONPATH}

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    build-essential \
    cmake \
    ninja-build \
    libsparsehash-dev \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY algorithms/bite_classification/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cu124 \
    torch==2.5.0 torchvision==0.20.0 torchaudio==2.5.0

RUN pip install --no-cache-dir \
    --find-links https://data.pyg.org/whl/torch-2.5.0+cu124.html \
    torch-scatter torch-sparse torch-cluster torch-geometric

RUN pip install --no-cache-dir spconv-cu124

COPY Bits2Bites /opt/Bits2Bites
COPY algorithms/bite_classification/scripts/build_pointcept_kernels.sh /app/scripts/build_pointcept_kernels.sh

RUN chmod +x /app/scripts/build_pointcept_kernels.sh && /app/scripts/build_pointcept_kernels.sh

COPY algorithms/bite_classification /app

RUN mkdir -p /app/models && cp /app/model_best.pth /app/models/model_best.pth

CMD ["sh", "-c", "python -m celery -A runner.celery_app worker -l info -Q ${RUNNER_QUEUE:-runner_bite_dev} --concurrency=1 --prefetch-multiplier=1 -O fair"]
