from queue import Queue, Empty
from threading import Thread

import time

import torch
from torch.autograd import Variable


class DataProvider:
    def __init__(self, iterator, batch_names, is_cuda=False, volatile=None, requires_grad=None, recode_functions=None):
        self.iterator = iterator
        self.batch_names = batch_names
        self.batch_index = 0
        self.is_cuda = is_cuda
        self.volatile = {} if volatile is None else volatile
        self.requires_grad = {} if requires_grad is None else requires_grad
        self.recode_functions = {} if recode_functions is None else recode_functions
        self.all_columns_to_keep=[]
        for batch_name in batch_names:
            if requires_grad is not None:
                for key in requires_grad[batch_name]:
                    self.all_columns_to_keep+=[key]
            if volatile is not None:
                for key in volatile[batch_name]:
                    self.all_columns_to_keep+=[key]
            if recode_functions is not None:
                for key in recode_functions:
                    self.all_columns_to_keep+=[key]
        self.all_columns_to_keep=set(self.all_columns_to_keep)
        print(self.all_columns_to_keep)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __iter__(self):
        return self

    def __next__(self):
        return self.__next_tuple__(is_cuda=self.is_cuda)

    def __next_tuple__(self, is_cuda):
        """
        This method returns the next batch of data, prepared for pytorch, on GPU when is_cuda is true, as variables.
        Use variable_kargs to pass arguments to the Variable calls.
        :return: Dictionary with named inputs and outputs.
        """
        data_dict = {}
        indices_dict = {}
        try:
            batch = next(self.iterator)
        except StopIteration:
            raise StopIteration

        for loader_index, (batch_indices, batch_data) in enumerate(batch):
            loader_name = self.batch_names[loader_index]
            data_dict[loader_name] = {}
            if len(self.requires_grad) == 0:
                self.requires_grad[loader_name] = []
            if len(self.volatile) == 0:
                self.volatile[loader_name] = []
            for var_name in batch_data.keys():
                if  var_name in self.all_columns_to_keep:
                    if var_name in self.recode_functions.keys():
                        batch_data[var_name] = self.recode_functions[var_name](batch_data[var_name])
                    if isinstance(batch_data[var_name],Variable):
                        # pass-through any batch data that is already a variable:
                        data_dict[loader_name][var_name]=batch_data[var_name]
                    else:
                        # if we have a tensor at this point, make it into a pytorch variable:
                        if torch.is_tensor (batch_data[var_name]):
                            var_batch = Variable(batch_data[var_name], requires_grad=(var_name in self.requires_grad[loader_name]),
                                             volatile=(var_name in self.volatile[loader_name]))
                            if is_cuda:
                                var_batch = var_batch.cuda(async=False)

                            data_dict[loader_name][var_name] = var_batch
                        else:
                            # just pass-through any other type of object:
                            data_dict[loader_name][var_name] =batch_data[var_name]
            indices_dict[loader_name] = batch_indices
        return indices_dict, data_dict

    def close(self):
        try:
            self.iterator.close()
        except:
           pass
        del self.iterator


class CpuGpuDataProvider(DataProvider):
    def __init__(self, iterator, batch_names, is_cuda=False, volatile=None, requires_grad=None, preload_n=3,
                 preload_cuda_n=3, fake_gpu_on_cpu=False, recode_functions=None):
        # do not put on GPU in super
        super(CpuGpuDataProvider, self).__init__(iterator=iterator, batch_names=batch_names, is_cuda=False,
                                                 volatile=volatile, requires_grad=requires_grad,
                                                 recode_functions=recode_functions)
        self.is_cuda = is_cuda
        self.cpu_batches_queue = Queue(maxsize=preload_n)
        self.batch_index = 0
        self.fake_gpu_on_cpu = fake_gpu_on_cpu
        if is_cuda or self.fake_gpu_on_cpu:
            self.gpu_batches_queue = Queue(maxsize=preload_cuda_n)

    def __next__(self):
        """
        This method returns the next batch of data, prepared for pytorch, on GPU when is_cuda is true.
        :return: Dictionary with named inputs and outputs.
        """
        while not self.gpu_batches_queue.full():
            self.populate_cpu_queue()
            self.populate_gpu_queue()

        self.batch_index += 1
        try:
            if self.is_cuda or self.fake_gpu_on_cpu:
                return self.gpu_batches_queue.get(block=True, timeout=3)
            else:
                return self.cpu_batches_queue.get(block=True, timeout=3)
        except Empty:
            raise StopIteration

    def populate_cpu_queue(self, recode_functions=None):
        # recode_functions = {} if recode_functions is None else recode_functions
        try:
            next_indices, next_data = self.__next_tuple__(False)
            # for batch_name in self.batch_names:
            #    batch = next_data[batch_name]
            #    for var_name in recode_functions.keys():
            #    if var_name in batch.keys():
            #        batch[var_name] = recode_functions[var_name](batch[var_name])
            self.cpu_batches_queue.put((next_indices, next_data), block=True)
        except StopIteration:
            raise StopIteration

    def populate_gpu_queue(self):
        batch_indices, batch_data = self.cpu_batches_queue.get(block=True)
        for batch_name in self.batch_names:
            batch = batch_data[batch_name]
            for var_name in batch.keys():
                if not self.fake_gpu_on_cpu:
                    if hasattr(batch[var_name],"cuda"):
                        batch[var_name] = batch[var_name].cuda()
        self.gpu_batches_queue.put((batch_indices, batch_data), block=True)


class MultiThreadedCpuGpuDataProvider(CpuGpuDataProvider):
    def __init__(self, iterator, batch_names, is_cuda=False, volatile=None, requires_grad=None, preload_n=20,
                 preload_cuda_n=20, recode_functions=None, fake_gpu_on_cpu=False):
        super().__init__(iterator, batch_names, is_cuda=is_cuda,
                         volatile=volatile, requires_grad=requires_grad, preload_n=preload_n,
                         preload_cuda_n=preload_cuda_n, fake_gpu_on_cpu=fake_gpu_on_cpu,
                         recode_functions=recode_functions)
        self.stop_iteration = False
        self.kill_threads = False

        def add_to_cpu_queue():
            while not self.kill_threads:
                try:
                    if not self.cpu_batches_queue.full():
                        self.populate_cpu_queue(recode_functions=recode_functions)
                    else:
                        time.sleep(10 / 1000.0)
                except StopIteration:
                    self.stop_iteration = True
                    break

        self.t1 = Thread(target=add_to_cpu_queue, name="BatchesToCPU")
        self.t1.start()

        while self.cpu_batches_queue.empty():
            time.sleep(10 / 1000.0)

        if is_cuda or self.fake_gpu_on_cpu:
            def add_to_gpu_queue():
                while not self.kill_threads:
                    if not self.gpu_batches_queue.full():
                        self.populate_gpu_queue()
                    else:
                        time.sleep(10 / 1000.0)

            self.t2 = Thread(target=add_to_gpu_queue, name="BatchesToGPU")
            self.t2.start()

            time.sleep(10 / 1000.0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __next__(self):
        """
        This method returns the next batch of data, prepared for pytorch, on GPU when is_cuda is true.
        :return: Dictionary with named inputs and outputs.
        """
        try:
            if self.is_cuda or self.fake_gpu_on_cpu:
                return self.gpu_batches_queue.get(block=True, timeout=3)
            else:
                return self.cpu_batches_queue.get(block=True, timeout=3)
        except Empty:
            raise StopIteration

    def close(self):
        super().close()
        self.kill_threads = True
        time.sleep(1)

    def queues_are_empty(self):
        return (self.cpu_batches_queue.empty()
                or ((self.is_cuda or self.fake_gpu_on_cpu)
                    and self.gpu_batches_queue.empty()
                    and self.cpu_batches_queue.empty()))
