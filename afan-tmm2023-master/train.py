# Copyright 2022 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""train"""

import logging
from mindspore import context
from mindspore.common import set_seed
from mindspore.train.model import Model
from mindspore.nn import Adam, ExponentialDecayLR
from mindspore.train.summary.summary_record import SummaryRecord
from mindspore.train.callback import ModelCheckpoint, CheckpointConfig, LossMonitor, TimeMonitor
from mindspore.train.serialization import load_checkpoint, load_param_into_net
from src.afan import AFAN, AFANWithLossCell
from src.loss import AFAN_Loss, get_mask
from src.config import config as cfg
from src.dataset import createDataset
from src.callbacks import CustomLossMonitor

if __name__ == '__main__':
    logging.basicConfig()
    logger = logging.getLogger(__name__)

    logger.info("Training configuration:\n\v%s\n\v", (cfg.__str__()))

    logger.setLevel(cfg.log_level)

    context.set_context(mode=context.PYNATIVE_MODE, device_target=cfg.platform, save_graphs=False)
    #datasets
    train_dataset, tem_train_dict = createDataset(cfg, mode='train')
    batch_num = train_dataset.get_dataset_size()

    #network
    
    network = AFAN(cfg.model)
    network_expert_1 = AFAN(cfg.model)
    network_expert_2 = AFAN(cfg.model)
    #checkpoint
    param_dict = load_checkpoint("/opt/data/private/yptang/codes/mindspore/TMM_AFAN/checkpoints/AFAN_expert1.ckpt")
    load_param_into_net(network_expert_1, param_dict)
    param_dict = load_checkpoint("/opt/data/private/yptang/codes/mindspore/TMM_AFAN/checkpoints/AFAN_expert2.ckpt")
    load_param_into_net(network_expert_2, param_dict)


    for param in network_expert_1.trainable_params():
        param_name = param.name
        if "bias" in param_name:
            param.requires_grad = False
    for param in network_expert_2.trainable_params():
        param_name = param.name
        if "bias" in param_name:
            param.requires_grad = False
    #lr
    lr = ExponentialDecayLR(cfg.train.learning_rate,
                            cfg.train.step_gamma,
                            cfg.train.step_size * batch_num,
                            is_stair=True)

    #optimizer
    opt = Adam(params=network.trainable_params(),
               learning_rate=lr,
               weight_decay=cfg.train.weight_decay)

    #AFAN specific
    bm_mask = get_mask(cfg.model.temporal_scale)

    #loss
    loss = AFAN_Loss(bm_mask, mode="train")

    # train net
    train_net = AFANWithLossCell(network, network_expert_1, network_expert_2, loss)

    #models
    model = Model(network=train_net,
                  optimizer=opt,
                  loss_fn=None,)

    #callbacks
    ckpt_save_dir = cfg.ckpt.save_dir
    config_ck = CheckpointConfig(save_checkpoint_steps=batch_num * 2,
                                 keep_checkpoint_max=cfg.ckpt.keep_checkpoint_max)

    ckpoint_cb = ModelCheckpoint(prefix="afan_auto_",
                                 directory=ckpt_save_dir,
                                 config=config_ck)
    time_cb = TimeMonitor(data_size=batch_num)
    loss_cb = LossMonitor()

    cbs = [time_cb, ckpoint_cb, loss_cb]

    #train
    with SummaryRecord(cfg.summary_save_dir) as summary_record:
        loss_cb = CustomLossMonitor(summary_record=summary_record,
                                    mode="train")

        cbs += [loss_cb]
        logger.info("Start training model")
        model.train(epoch=cfg.train.epoch,
                    train_dataset=train_dataset,
                    callbacks=cbs,
                    dataset_sink_mode=False)

    logger.info("Exp. %s - AFAN train success", (cfg.experiment_name))
