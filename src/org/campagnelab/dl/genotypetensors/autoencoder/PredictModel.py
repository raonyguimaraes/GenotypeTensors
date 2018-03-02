import sys

from torch.utils.data import DataLoader

from org.campagnelab.dl.genotypetensors.VectorWriterBinary import VectorWriterBinary
from org.campagnelab.dl.genotypetensors.genotype_pytorch_dataset import MultiProcessingPredictDataset, PartitionedPredictDataset
from org.campagnelab.dl.multithreading.sequential_implementation import MultiThreadedCpuGpuDataProvider, DataProvider
from org.campagnelab.dl.utils.utils import progress_bar


class PredictModel:
    def __init__(self, model, use_cuda, problem, domain_descriptor=None,
                 feature_mapper=None, samples=None, input_files=None, processing_type="multithreaded",
                 num_workers=0):
        self.model = model
        self.use_cuda = use_cuda
        self.problem = problem
        self.mini_batch_size = problem.mini_batch_size()
        self.domain_descriptor = domain_descriptor
        self.feature_mapper = feature_mapper
        self.samples = samples
        self.input_files = input_files
        self.processing_type = processing_type
        self.num_workers = num_workers

    def predict(self, iterator, output_filename, max_examples=sys.maxsize):

        self.model.eval()
        if self.processing_type == "multithreaded":
            data_provider = MultiThreadedCpuGpuDataProvider(iterator=zip(iterator),
                                                            is_cuda=self.use_cuda,
                                                            batch_names=["unlabeled"],
                                                            volatile={"unlabeled": ["input"]},
                                                            fake_GPU_on_CPU = False)  # Enable fake_GPU_on_CPU to debug on CPU

        elif self.processing_type == "sequential":
            data_provider = DataProvider(iterator=zip(iterator),
                                         is_cuda=self.use_cuda,
                                         batch_names=["unlabeled"],
                                         volatile={"unlabeled": ["input"]})
        else:
            if self.processing_type == "parallel":
                dataset = MultiProcessingPredictDataset(self.problem.basename, self.problem.get_vector_names(),
                                                        cache_first=True, use_cuda=self.use_cuda)
            elif self.processing_type == "partitioned":
                dataset = PartitionedPredictDataset(self.problem.basename, self.problem.get_vector_names(),
                                                    cache_first=True, use_cuda=self.use_cuda,
                                                    num_workers=self.num_workers)
            else:
                raise Exception("Unrecognized processing type {}".format(self.processing_type))
            data_provider = DataLoader(dataset, batch_size=self.mini_batch_size, num_workers=self.num_workers)

        with VectorWriterBinary(sample_id=0, path_with_basename=output_filename,
                                tensor_names=self.problem.get_output_names(),
                                domain_descriptor=self.domain_descriptor, feature_mapper=self.feature_mapper,
                                samples=self.samples, input_files=self.input_files) as writer:
            for batch_idx, data_dict in enumerate(data_provider):
                if self.processing_type == "multithreaded" or self.processing_type == "sequential":
                    input_u = data_dict["unlabeled"]["input"]
                else:
                    input_u = data_dict["input"]

                outputs = self.model(input_u)
                writer.append(0, outputs, inverse_logit=True)
                progress_bar(batch_idx * self.mini_batch_size, max_examples)

                if ((batch_idx + 1) * self.mini_batch_size) > max_examples:
                    break
        if self.processing_type == "multithreaded" or self.processing_type == "sequential":
            data_provider.close()
        print("Done")
