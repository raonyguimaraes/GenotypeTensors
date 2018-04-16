#!/usr/bin/env bash
export SBI_SEARCH_PARAM_CONFIG=${GENOTYPE_TENSORS}/config/final-search-hyperparam-supervised-funnel.txt
export CUDA_VISIBLE_DEVICES=0
mkdir -p search/supervised/direct
(cd search/supervised/direct
${GENOTYPE_TENSORS}/bin/search-hyperparameters.sh 64 --problem genotyping:CNG-NA12878-realigned-2018-01-30 --mode supervised-direct --num-workers 4  --num-models-per-gpu 32 &
)

export SBI_SEARCH_PARAM_CONFIG=config/initial-search-hyperparam-supervised-funnel-mixup.txt
export CUDA_VISIBLE_DEVICES=2
mkdir -p search/supervised/mixup
(cd search/supervised/mixup
${GENOTYPE_TENSORS}/bin/search-hyperparameters.sh 64 --problem genotyping:CNG-NA12878-realigned-2018-01-30 --mode supervised-direct --num-workers 4  --num-models-per-gpu 32 &
)

export SBI_SEARCH_PARAM_CONFIG=config/initial-search-hyperparam-semisupervised-autoencoder.txt
export CUDA_VISIBLE_DEVICES=4
mkdir -p search/semisupervised/aae
(cd search/semisupervised/aae
${GENOTYPE_TENSORS}/bin/search-hyperparameters.sh 64 --problem genotyping:CNG-NA12878-realigned-2018-01-30 --mode semisupervised --num-workers 4  --num-models-per-gpu 32 &
)