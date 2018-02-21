from torch.autograd import Variable
from torch.nn import MSELoss, BCELoss, BCEWithLogitsLoss, NLLLoss, MultiLabelSoftMarginLoss

from org.campagnelab.dl.genotypetensors.autoencoder.common_trainer import CommonTrainer
from org.campagnelab.dl.multithreading.sequential_implementation import DataProvider, CpuGpuDataProvider, \
    MultiThreadedCpuGpuDataProvider
from org.campagnelab.dl.performance.FloatHelper import FloatHelper
from org.campagnelab.dl.performance.LossHelper import LossHelper
from org.campagnelab.dl.performance.PerformanceList import PerformanceList
from org.campagnelab.dl.utils.utils import progress_bar


class GenotypingSupervisedTrainer(CommonTrainer):
    """Train a genotyping model using supervised training only."""
    def __init__(self, args, problem, use_cuda):
        super().__init__(args, problem, use_cuda)
        self.criterion_classifier = MultiLabelSoftMarginLoss()

    def get_test_metric_name(self):
        return "test_supervised_loss"

    def is_better(self, metric, previous_metric):
        return metric< previous_metric

    def train_supervised(self, epoch):

        performance_estimators = PerformanceList()
        performance_estimators += [FloatHelper("supervised_loss")]

        print('\nTraining, epoch: %d' % epoch)

        self.net.train()

        for performance_estimator in performance_estimators:
            performance_estimator.init_performance_metrics()

        unsupervised_loss_acc = 0
        num_batches = 0
        train_loader_subset = self.problem.train_loader_subset_range(0, self.args.num_training)
        data_provider = MultiThreadedCpuGpuDataProvider(iterator=zip(train_loader_subset),is_cuda=self.use_cuda,
                                     batch_names=["training"],
                                     requires_grad={"training": ["input"]},
                                     volatile={"training": [] })
        self.net.autoencoder.train()
        for batch_idx, dict in enumerate(data_provider):
            input_s = dict["training"]["input"]
            target_s = dict["training"]["softmaxGenotype"]

            num_batches += 1

            # outputs used to calculate the loss of the supervised model
            # must be done with the model prior to regularization:

            self.optimizer_training.zero_grad()
            self.net.zero_grad()
            output_s = self.net(input_s)

            supervised_loss = self.criterion_classifier(output_s, target_s)
            optimized_loss = supervised_loss
            optimized_loss.backward()
            self.optimizer_training.step()
            performance_estimators.set_metric(batch_idx, "supervised_loss", supervised_loss.data[0])

            progress_bar(batch_idx * self.mini_batch_size,
                         self.max_training_examples,
                         performance_estimators.progress_message(["supervised_loss", "reconstruction_loss"]))

            if (batch_idx + 1) * self.mini_batch_size > self.max_training_examples:
                break
        data_provider.close()

        return performance_estimators

    def test_supervised(self, epoch):
        print('\nTesting, epoch: %d' % epoch)

        performance_estimators = PerformanceList()
        performance_estimators += [LossHelper("test_supervised_loss")]

        self.net.eval()
        for performance_estimator in performance_estimators:
            performance_estimator.init_performance_metrics()
        validation_loader_subset=self.problem.validation_loader_range(0, self.args.num_validation)
        data_provider = MultiThreadedCpuGpuDataProvider(iterator=zip(validation_loader_subset), is_cuda=self.use_cuda,
                                     batch_names=["validation"],
                                     requires_grad={"validation": []},
                                     volatile={"validation": ["input","softmaxGenotype"]})
        for batch_idx, dict in enumerate(data_provider):
            input_s = dict["validation"]["input"]
            target_s = dict["validation"]["softmaxGenotype"]

            output_s = self.net(input_s)
            supervised_loss = self.criterion_classifier(output_s, target_s)

            performance_estimators.set_metric(batch_idx, "test_supervised_loss", supervised_loss.data[0])
            progress_bar(batch_idx * self.mini_batch_size, self.max_validation_examples,
                         performance_estimators.progress_message(["test_supervised_loss","test_reconstruction_loss"]))

            if ((batch_idx + 1) * self.mini_batch_size) > self.max_validation_examples:
                break
        # print()
        data_provider.close()
        # Apply learning rate schedule:
        test_accuracy = performance_estimators.get_metric("test_supervised_loss")
        assert test_accuracy is not None, "test_supervised_loss must be found among estimated performance metrics"
        if not self.args.constant_learning_rates:
            self.scheduler_train.step(test_accuracy, epoch)
        return performance_estimators
