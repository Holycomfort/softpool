from __future__ import print_function
import torch
import torch.nn as nn
import torch.nn.parallel
import torch.utils.data
from torch.autograd import Variable
import numpy as np
import torch.nn.functional as F
import sys
sys.path.append("./expansion_penalty/")
import expansion_penalty_module as expansion
sys.path.append("./MDS/")
import MDS_module


def SoftPool(x, N_p=32):
    featdim = list(x.shape)[1]
    bth_size = list(x.shape)[0]
    sp_cube = torch.zeros(bth_size, featdim, N_p, featdim).cuda()
    for idx in range(featdim):
        x_val, x_idx = torch.sort(x[:, idx, :], dim=1, descending=True)
        index = x_idx[:, :N_p].unsqueeze(1).repeat(1, featdim, 1)
        sp_cube[:, :, :, idx] = torch.gather(x, dim=2, index=index)
    return sp_cube


class STN3d(nn.Module):
    def __init__(self, num_points=2500, dim_pn=256):
        super(STN3d, self).__init__()
        self.num_points = num_points
        self.conv1 = torch.nn.Conv1d(3, 64, 1)
        self.conv2 = torch.nn.Conv1d(64, 128, 1)
        self.conv3 = torch.nn.Conv1d(128, dim_pn, 1)
        self.fc1 = nn.Linear(dim_pn, 512)
        self.fc2 = nn.Linear(512, 256)
        self.fc3 = nn.Linear(256, 9)
        self.relu = nn.ReLU()

    def forward(self, x):
        batchsize = x.size()[0]
        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = F.relu(self.conv3(x))
        x, _ = torch.max(x, 2)
        x = x.view(-1, dim_pn)

        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = self.fc3(x)

        iden = Variable(
            torch.from_numpy(
                np.array([1, 0, 0, 0, 1, 0, 0, 0,
                          1]).astype(np.float32))).view(1, 9).repeat(
                              batchsize, 1)
        if x.is_cuda:
            iden = iden.cuda()
        x = x + iden
        x = x.view(-1, 3, 3)
        return x


class PointNetfeat(nn.Module):
    def __init__(self, num_points=8192, global_feat=True, dim_pn=256):
        super(PointNetfeat, self).__init__()
        self.stn = STN3d(num_points=num_points)
        self.dim_pn = dim_pn
        self.conv1 = torch.nn.Conv1d(3, 64, 1)
        self.conv2 = torch.nn.Conv1d(64, 128, 1)
        self.conv3 = torch.nn.Conv1d(128, dim_pn, 1)

        self.bn1 = torch.nn.BatchNorm1d(64)
        self.bn2 = torch.nn.BatchNorm1d(128)
        self.bn3 = torch.nn.BatchNorm1d(dim_pn)

        self.num_points = num_points
        self.global_feat = global_feat

    def forward(self, x):
        batchsize = x.size()[0]
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = self.bn3(self.conv3(x))
        x, _ = torch.max(x, 2)
        x = x.view(-1, self.dim_pn)
        return x


class SoftPoolfeat(nn.Module):
    def __init__(self, num_points=8192, global_feat=True, dim_pn=256, N_p=32):
        super(SoftPoolfeat, self).__init__()
        self.stn = STN3d(num_points=num_points)
        self.conv1 = torch.nn.Conv1d(3, 64, 1)
        self.conv2 = torch.nn.Conv1d(64, 128, 1)
        self.conv3 = torch.nn.Conv1d(128, dim_pn, 1)

        self.bn1 = torch.nn.BatchNorm1d(64)
        self.bn2 = torch.nn.BatchNorm1d(128)
        self.bn3 = torch.nn.BatchNorm1d(dim_pn)

        self.num_points = num_points
        self.global_feat = global_feat
        self.N_p = N_p

    def forward(self, x):
        batchsize = x.size()[0]
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = self.bn3(self.conv3(x))
        x = SoftPool(x, N_p=self.N_p)
        return x


class PointGenCon(nn.Module):
    def __init__(self, bottleneck_size=8192):
        self.bottleneck_size = bottleneck_size
        super(PointGenCon, self).__init__()
        self.conv1 = torch.nn.Conv1d(self.bottleneck_size,
                                     self.bottleneck_size, 1)
        self.conv2 = torch.nn.Conv1d(self.bottleneck_size,
                                     self.bottleneck_size // 2, 1)
        self.conv3 = torch.nn.Conv1d(self.bottleneck_size // 2,
                                     self.bottleneck_size // 4, 1)
        self.conv4 = torch.nn.Conv1d(self.bottleneck_size // 4, 3, 1)

        self.th = nn.Tanh()
        self.bn1 = torch.nn.BatchNorm1d(self.bottleneck_size)
        self.bn2 = torch.nn.BatchNorm1d(self.bottleneck_size // 2)
        self.bn3 = torch.nn.BatchNorm1d(self.bottleneck_size // 4)

    def forward(self, x):
        batchsize = x.size()[0]
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = F.relu(self.bn3(self.conv3(x)))
        x = self.th(self.conv4(x))
        return x


class PointNetRes(nn.Module):
    def __init__(self):
        super(PointNetRes, self).__init__()
        self.conv1 = torch.nn.Conv1d(4, 64, 1)
        self.conv2 = torch.nn.Conv1d(64, 128, 1)
        # self.conv3 = torch.nn.Conv1d(128, 1024, 1)
        # self.conv4 = torch.nn.Conv1d(1088, 512, 1)
        self.conv3 = torch.nn.Conv1d(128, 256, 1)
        self.conv4 = torch.nn.Conv1d(320, 512, 1)
        self.conv5 = torch.nn.Conv1d(512, 256, 1)
        self.conv6 = torch.nn.Conv1d(256, 128, 1)
        self.conv7 = torch.nn.Conv1d(128, 3, 1)

        self.bn1 = torch.nn.BatchNorm1d(64)
        self.bn2 = torch.nn.BatchNorm1d(128)
        # self.bn3 = torch.nn.BatchNorm1d(1024)
        self.bn3 = torch.nn.BatchNorm1d(256)
        self.bn4 = torch.nn.BatchNorm1d(512)
        self.bn5 = torch.nn.BatchNorm1d(256)
        self.bn6 = torch.nn.BatchNorm1d(128)
        self.bn7 = torch.nn.BatchNorm1d(3)
        self.th = nn.Tanh()

        # softpool
        self.N_p = 32
        self.dim_pn = 256
        self.bottleneck_size = 256
        self.conv8 = torch.nn.Conv2d(
            self.dim_pn,
            self.bottleneck_size,
            kernel_size=(1, self.dim_pn),
            stride=(1, 1))
        self.conv9 = torch.nn.Conv2d(
            self.bottleneck_size,
            self.bottleneck_size,
            kernel_size=(self.N_p, 1),
            stride=(1, 1))
        self.flat = nn.Flatten()

    def forward(self, x):
        batchsize = x.size()[0]
        npoints = x.size()[2]
        x = F.relu(self.bn1(self.conv1(x)))
        pointfeat = x
        x = F.relu(self.bn2(self.conv2(x)))
        x = self.bn3(self.conv3(x))
        # x,_ = torch.max(x, 2)
        # softpoool
        """
        x = self.sp(x)
        x = self.flatten(x)
        """
        # x = x.view(-1, 1024)
        # x = x.view(-1, 1024, 1).repeat(1, 1, npoints)
        x = SoftPool(x)
        self.softpool = x
        x = self.conv8(x)
        x = self.conv9(x)
        x = x.view(-1, 256)
        x = x.view(-1, 256, 1).repeat(1, 1, npoints)
        # end
        x = torch.cat([x, pointfeat], 1)
        x = F.relu(self.bn4(self.conv4(x)))
        x = F.relu(self.bn5(self.conv5(x)))
        x = F.relu(self.bn6(self.conv6(x)))
        x = self.th(self.conv7(x))
        return x


class MSN(nn.Module):
    def __init__(self,
                 num_points=8192,
                 bottleneck_size=256,
                 n_primitives=16,
                 dim_pn=256):
        super(MSN, self).__init__()
        self.num_points = num_points
        self.bottleneck_size = bottleneck_size
        self.n_primitives = n_primitives
        """
        self.encoder = nn.Sequential(
        PointNetfeat(num_points, global_feat=True),
        nn.Linear(dim_pn, self.bottleneck_size),
        nn.BatchNorm1d(self.bottleneck_size),
        nn.ReLU()
        )
        """
        self.N_p = 32
        self.encoder = nn.Sequential(
            SoftPoolfeat(num_points, global_feat=True, N_p=self.N_p),
            # nn.Linear(dim_pn, 1),
            nn.Linear(dim_pn, self.n_primitives),
            nn.Conv2d(
                dim_pn,
                bottleneck_size,
                kernel_size=(self.N_p, 1),
                stride=(1, 1)),
            nn.Flatten(start_dim=2, end_dim=3),
            # nn.Flatten(),
            nn.BatchNorm1d(bottleneck_size),
            nn.ReLU())
        self.decoder = nn.ModuleList([
            PointGenCon(bottleneck_size=2 + self.bottleneck_size)
            for i in range(0, self.n_primitives)
        ])
        self.res = PointNetRes()
        self.expansion = expansion.expansionPenaltyModule()

    def forward(self, x):
        partial = x
        x = self.encoder(x)
        outs = []
        for i in range(0, self.n_primitives):
            rand_grid = Variable(
                torch.cuda.FloatTensor(
                    x.size(0), 2, self.num_points // self.n_primitives))
            rand_grid.data.uniform_(0, 1)
            # y = x.unsqueeze(2).expand(x.size(0),x.size(1), rand_grid.size(2)).contiguous()
            y = x[:, :, i].unsqueeze(2).expand(
                x.size(0), x.size(1), rand_grid.size(2)).contiguous()
            y = torch.cat((rand_grid, y), 1).contiguous()
            outs.append(self.decoder[i](y))

        outs = torch.cat(outs, 2).contiguous()
        out1 = outs.transpose(1, 2).contiguous()

        dist, _, mean_mst_dis = self.expansion(
            out1, self.num_points // self.n_primitives, 1.5)
        loss_mst = torch.mean(dist)

        id0 = torch.zeros(outs.shape[0], 1, outs.shape[2]).cuda().contiguous()
        outs = torch.cat((outs, id0), 1)
        id1 = torch.ones(partial.shape[0], 1,
                         partial.shape[2]).cuda().contiguous()
        partial = torch.cat((partial, id1), 1)
        xx = torch.cat((outs, partial), 2)

        resampled_idx = MDS_module.minimum_density_sample(
            xx[:, 0:3, :].transpose(1, 2).contiguous(), out1.shape[1],
            mean_mst_dis)
        xx = MDS_module.gather_operation(xx, resampled_idx)
        delta = self.res(xx)
        xx = xx[:, 0:3, :]
        out2 = (xx + delta).transpose(2, 1).contiguous()
        return out1, out2, loss_mst, self.res.softpool
