from torch.autograd import Variable
from torch.nn import MSELoss, BCELoss, BCEWithLogitsLoss

from org.campagnelab.dl.genotypetensors.autoencoder.common_trainer import CommonTrainer
from org.campagnelab.dl.performance.FloatHelper import FloatHelper
from org.campagnelab.dl.performance.LossHelper import LossHelper
from org.campagnelab.dl.performance.PerformanceList import PerformanceList
from org.campagnelab.dl.utils.utils import progress_bar, grad_norm


class GenotypingSemiSupTrainer(CommonTrainer):
    """Train a genotyping model using supervised and reconstruction on unlabeled set."""
    def __init__(self, args, problem, use_cuda):
        super().__init__(args, problem, use_cuda)
        self.criterion_autoencoder = MSELoss()
        self.criterion_classifier = BCEWithLogitsLoss()

    def get_test_metric_name(self):
        return "test_supervised_loss"

    def is_better(self, metric, previous_metric):
        return metric< previous_metric

    def train_semisup(self, epoch):

        performance_estimators = PerformanceList()
        performance_estimators += [FloatHelper("optimized_loss")]
        performance_estimators += [FloatHelper("supervised_loss")]
        performance_estimators += [FloatHelper("reconstruction_loss")]

        print('\nTraining, epoch: %d' % epoch)

        self.net.train()
        supervised_grad_norm = 1.
        for performance_estimator in performance_estimators:
            performance_estimator.init_performance_metrics()

        unsupervised_loss_acc = 0
        num_batches = 0
        train_loader_subset = self.problem.train_loader_subset_range(0, self.args.num_training)
        unlabeled_loader = self.problem.unlabeled_loader()

        for batch_idx, (dict_training, dict_unlabeled) in enumerate(zip(train_loader_subset, unlabeled_loader)):
            input_s = dict_unlabeled["input"]
            target_s = dict_unlabeled["softmaxGenotype"]
            input_u = dict_unlabeled["input"]
            num_batches += 1

            if self.use_cuda:
                input_s, target_s, input_u = input_s.cuda(), target_s.cuda(), input_u.cuda()

            input_s, target_s, input_u, target_u = Variable(input_s), Variable(target_s), Variable(input_u), \
                                                   Variable(input_u, requires_grad=False)
            # outputs used to calculate the loss of the supervised model
            # must be done with the model prior to regularization:
            self.net.train()
            self.net.autoencoder.train()
            self.optimizer_training.zero_grad()
            output_s = self.net(input_s)
            output_u = self.net.autoencoder(input_u)

            supervised_loss = self.criterion_classifier(output_s, target_s)
            reconstruction_loss = self.criterion_autoencoder(output_u, target_u)
            optimized_loss = supervised_loss + self.args.gamma * reconstruction_loss
            optimized_loss.backward()
            self.optimizer_training.step()
            performance_estimators.set_metric(batch_idx, "supervised_loss", supervised_loss.data[0])
            performance_estimators.set_metric(batch_idx, "reconstruction_loss", reconstruction_loss.data[0])
            performance_estimators.set_metric(batch_idx, "train_grad_norm", supervised_grad_norm)
            performance_estimators.set_metric(batch_idx, "optimized_loss", optimized_loss.data[0])

            progress_bar(batch_idx * self.mini_batch_size,
                         self.max_training_examples,
                         performance_estimators.progress_message(["supervised_loss", "reconstruction_loss"]))

            if (batch_idx + 1) * self.mini_batch_size > self.max_training_examples:
                break

        return performance_estimators

    def test_semi_sup(self, epoch):
        print('\nTesting, epoch: %d' % epoch)

        performance_estimators = PerformanceList()
        performance_estimators += [LossHelper("test_supervised_loss")]
        performance_estimators += [LossHelper("test_reconstruction_loss")]

        self.net.eval()
        for performance_estimator in performance_estimators:
            performance_estimator.init_performance_metrics()

        for batch_idx, dict in enumerate(self.problem.validation_loader_range(0, self.args.num_validation)):
            inputs = dict["input"]
            targets = dict["softmaxGenotype"]
            if self.use_cuda:
                inputs, targets = inputs.cuda(), targets.cuda()

            input_s, target_s, input_u, target_u = Variable(inputs, volatile=True), Variable(targets, volatile=True),\
                                                   Variable(inputs, volatile=True), Variable(inputs, volatile=True)

            output_s = self.net(input_s)
            output_u = self.net.autoencoder(input_u)
            supervised_loss = self.criterion_classifier(output_s, target_s)
            reconstruction_loss = self.criterion_autoencoder(output_u, target_u)

            performance_estimators.set_metric(batch_idx, "test_supervised_loss", supervised_loss.data[0])
            performance_estimators.set_metric(batch_idx, "test_reconstruction_loss", reconstruction_loss.data[0])

            progress_bar(batch_idx * self.mini_batch_size, self.max_validation_examples,
                         performance_estimators.progress_message(["test_supervised_loss","test_reconstruction_loss"]))

            if ((batch_idx + 1) * self.mini_batch_size) > self.max_validation_examples:
                break
        # print()

        # Apply learning rate schedule:
        test_accuracy = performance_estimators.get_metric("test_supervised_loss")
        assert test_accuracy is not None, "test_supervised_loss must be found among estimated performance metrics"
        if not self.args.constant_learning_rates:
            self.scheduler_train.step(test_accuracy, epoch)
        return performance_estimators