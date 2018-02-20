import argparse
import csv

import os
import torch

if __name__ == "__main__":
    parser = argparse.ArgumentParser("Log results from evaluation script")
    parser.add_argument('--checkpoint-key', help='Random key to load a checkpoint model', required=True, type=str)
    parser.add_argument('--model-path', help='Path of where the models directory is located.', required=True, type=str)
    parser.add_argument('--model-label', help='Model label: best or latest.', default="best", type=str)
    parser.add_argument("--vcf-path", help="Path to base output directory for rtg vcfeval", type=str, required=True)
    parser.add_argument("--output-path", help="Location of log file; if file not present, creates a new CSV file",
                        type=str, required=True)
    args = parser.parse_args()

    print('==> Loading model from checkpoint..')
    assert os.path.isdir('{}/models/'.format(args.model_path)), 'Error: no models directory found!'
    checkpoint = None
    try:
        checkpoint_filename = '{}/models/pytorch_{}_{}.t7'.format(args.model_path, args.checkpoint_key,
                                                                  args.model_label)
        checkpoint = torch.load(checkpoint_filename)
    except FileNotFoundError:
        print("Unable to load model {} from checkpoint".format(args.checkpoint_key))
        exit(1)
    epoch = checkpoint['epoch']

    snp_summary_path = os.path.join(args.vcf_path, "snp", "summary.txt")
    indel_summary_path = os.path.join(args.vcf_path, "indel", "summary.txt")
    with open(snp_summary_path, "r") as snp_summary_f, open(indel_summary_path, "r") as indel_summary_f:
        snp_f1 = list(map(float, snp_summary_f.readlines()[2].strip().split()))[-1]
        indel_f1 = list(map(float, indel_summary_f.readlines()[2].strip().split()))[-1]

    file_exists = os.path.exists(args.output_path)
    fieldnames = ["path", "checkpoint", "label", "epoch", "F1_SNPs", "F1_Indels"]
    with open(args.output_path, "a") as output_f:
        output_writer = csv.DictWriter(output_f, fieldnames=fieldnames, delimiter="\t")
        if not file_exists:
            output_writer.writeheader()
        output_writer.writerow({
            "path": args.model_path,
            "checkpoint": args.checkpoint_key,
            "label": args.model_label,
            "epoch": epoch,
            "F1_SNPs": snp_f1,
            "F1_Indels": indel_f1
        })
