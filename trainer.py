import os
import random
import time
import torch
import torch.nn as nn
from torch import optim
from torch.autograd import Variable

from model import Classifier, SimilarityClassifier
from utils import map_label_to_target


def add_log(filepath, text=''):
    with open(filepath, 'a') as fd:
        fd.write(text + '\n')
    print(text)


def train(task,
          phase,
          num_class,
          num_words,
          logs_dir,
          models_dir,
          datafolds,
          seed,
          num_folds=10,
          glove=None,
          epochs=20,
          batch_size=25,
          input_size=100,
          hidden_size=50,
          lr=0.008,
          lr_milestones=None,
          weight_decay=1e-4,
          log_iteration_interval=500,
          use_gpu=False):
    config_string = '{}_{}_batchsize{}_input{}_hidden{}_lr{}{}_wc{}{}_seed{}'.format(
        task, phase, batch_size, input_size, hidden_size, lr,
        '' if not lr_milestones
        else '_ms' + ','.join([str(i) for i in lr_milestones]),
        weight_decay, '_glove' if glove is not None else '', seed)
    log_train_path = os.path.join(logs_dir,
                                  'train_{}.txt'.format(config_string))
    log_eval_path = os.path.join(logs_dir, 'eval_{}.txt'.format(config_string))
    print('[INFO] {}'.format(config_string))

    if task == 'TREC':
        classifier = Classifier(input_size, hidden_size, num_class, num_words,
                            glove, use_gpu)
        criterion = nn.CrossEntropyLoss()
    elif task == 'SICK':
        classifier = SimilarityClassifier(input_size, hidden_size, hidden_dim=50,
                                          num_class=num_class, vocab_size=num_words,
                                          glove=glove, use_gpu=use_gpu)
        criterion = nn.KLDivLoss()
    else:
        raise NotImplementedError

    if use_gpu:
        classifier = classifier.cuda()
        criterion = criterion.cuda()
    optimizer = optim.Adam(
        [p for p in classifier.parameters() if p.requires_grad],
        lr=lr,
        weight_decay=weight_decay)
    dataset_train = list()
    for i in range(num_folds - 1):
        dataset_train += datafolds[i]
    dataset_eval = datafolds[-1]
    scheduler = None if not lr_milestones else optim.lr_scheduler.MultiStepLR(
        optimizer, lr_milestones, gamma=0.5)

    print('train dataset size: {}'.format(len(dataset_train)))
    print('test dataset size: {}'.format(len(dataset_eval)))
    # train
    for epoch in range(epochs):
        if scheduler is not None:
            scheduler.step()
        random.shuffle(dataset_train)
        optimizer.zero_grad()
        log_loss = 0

        len_dataset_train = len(dataset_train)
        for iteration in range(1, len_dataset_train + 1):
            if task == 'TREC':
                tree_root, label = dataset_train[iteration - 1]
                output = classifier(tree_root)
                target = Variable(torch.LongTensor([label]), requires_grad=False)
                if use_gpu:
                    target = Variable(
                        torch.LongTensor([label]).cuda(), requires_grad=False)
            elif task == 'SICK':
                ltree, rtree, label = dataset_train[iteration - 1]
                output = classifier(ltree, rtree)
                target = map_label_to_target(label, num_class)
                target = torch.FloatTensor(target).cuda()
                target = Variable(target, requires_grad=False)

            loss = criterion(output, target)
            loss.backward()
            if iteration % batch_size == 0:
                optimizer.step()
                optimizer.zero_grad()
            # log
            log_loss += loss.data[0] / log_iteration_interval
            if iteration % log_iteration_interval == 0:
                add_log(log_train_path, '{} {} {}'.format(
                    time.ctime(), iteration, log_loss))
                log_loss = 0
        # evaluate
        if task == 'TREC':
            correct, total = classifier.evalute_dataset(dataset_eval)
            add_log(log_eval_path, '{} / {} = {:.3f}'.format(
                correct, total,
                float(correct) / total))
        elif task == 'SICK':
            pearson, mse, spearman = classifier.evalute_dataset(dataset_eval)
            add_log(log_eval_path, 'pearson: {}, mse: {}, spearman: {}'.format(pearson, mse, spearman))
        # save checkpoint
        checkpoint = {
            'model': classifier.state_dict(),
            'optimizer': optimizer,
            'epoch': epoch,
            'config_string': config_string
        }
        checkpoint_path = os.path.join(models_dir, '{}_epoch{}.pth'.format(
            config_string, epoch))
        torch.save(checkpoint, checkpoint_path)
