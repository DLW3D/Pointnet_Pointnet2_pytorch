import os
import numpy as np

from tqdm import tqdm
from torch.utils.data import Dataset
from data_utils.ply import read_ply


class DublinDataset(Dataset):
    def __init__(self, split='train', data_root='trainval_fullarea', num_point=4096, block_size=1.0, sample_rate=1.0, transform=None):
        super().__init__()
        self.num_point = num_point
        self.block_size = block_size
        self.transform = transform
        self.ignore_labels = [0]
        rooms = sorted(os.listdir(data_root))
        rooms = [room for room in rooms if 'ply' in room]
        if split == 'train':
            rooms_split = rooms[:-3]    # + rooms[-1:]
        else:
            rooms_split = rooms[-3:-1]

        self.room_points, self.room_labels = [], []
        self.room_coord_min, self.room_coord_max = [], []
        num_point_all = []
        labelweights = np.zeros(6 - len(self.ignore_labels))

        for room_name in tqdm(rooms_split, total=len(rooms_split)):
            room_path = os.path.join(data_root, room_name)
            data = read_ply(room_path)
            points = np.vstack([data['x'], data['y'], data['z'], data['red'], data['green'], np.ones_like(data['red'])]).T
            labels = data['class']
            tmp, _ = np.histogram(labels, range(7))
            labelweights += [tmp[i] for i in range(len(tmp)) if i not in self.ignore_labels]
            coord_min, coord_max = np.amin(points, axis=0)[:3], np.amax(points, axis=0)[:3]
            self.room_points.append(points), self.room_labels.append(labels)
            self.room_coord_min.append(coord_min), self.room_coord_max.append(coord_max)
            num_point_all.append(labels.size)
        labelweights = labelweights.astype(np.float32)
        labelweights = labelweights / np.sum(labelweights)
        self.labelweights = np.power(np.amax(labelweights) / labelweights, 1 / 3.0)
        print(self.labelweights)
        sample_prob = num_point_all / np.sum(num_point_all)
        num_iter = int(np.sum(num_point_all) * sample_rate / num_point)
        room_idxs = []
        for index in range(len(rooms_split)):
            room_idxs.extend([index] * int(round(sample_prob[index] * num_iter)))
        self.room_idxs = np.array(room_idxs)
        print("Totally {} samples in {} set.".format(len(self.room_idxs), split))

    def __getitem__(self, idx):
        room_idx = self.room_idxs[idx]
        points = self.room_points[room_idx]   # N * 6
        labels = self.room_labels[room_idx]   # N
        N_points = points.shape[0]

        while (True):
            center = points[np.random.choice(N_points)][:3]
            block_min = center - [self.block_size / 2.0, self.block_size / 2.0, 0]
            block_max = center + [self.block_size / 2.0, self.block_size / 2.0, 0]
            point_idxs = np.where((points[:, 0] >= block_min[0]) & (points[:, 0] <= block_max[0]) & (points[:, 1] >= block_min[1]) & (points[:, 1] <= block_max[1]))[0]
            if point_idxs.size > self.num_point // 4:
                break

        if point_idxs.size >= self.num_point:
            selected_point_idxs = np.random.choice(point_idxs, self.num_point, replace=False)
        else:
            selected_point_idxs = np.random.choice(point_idxs, self.num_point, replace=True)

        # normalize
        selected_points = points[selected_point_idxs, :]  # num_point * 6
        current_points = np.zeros((self.num_point, 9))  # num_point * 9
        current_points[:, 6] = selected_points[:, 0] / self.room_coord_max[room_idx][0]
        current_points[:, 7] = selected_points[:, 1] / self.room_coord_max[room_idx][1]
        current_points[:, 8] = selected_points[:, 2] / self.room_coord_max[room_idx][2]
        selected_points[:, 0] = selected_points[:, 0] - center[0]
        selected_points[:, 1] = selected_points[:, 1] - center[1]
        # selected_points[:, 3:6] /= 255.0
        current_points[:, 0:6] = selected_points
        current_labels = labels[selected_point_idxs]
        if self.transform is not None:
            current_points, current_labels = self.transform(current_points, current_labels)
        return current_points, current_labels

    def __len__(self):
        return len(self.room_idxs)

class ScannetDatasetWholeScene():
    # prepare to give prediction on each points
    def __init__(self, root, block_points=4096, split='test', test_area=5, stride=0.5, block_size=1.0, padding=0.001):
        self.block_points = block_points
        self.block_size = block_size
        self.padding = padding
        self.root = root
        self.split = split
        self.stride = stride
        self.scene_points_num = []
        assert split in ['train', 'test']
        self.ignore_labels = [0]
        rooms = sorted(os.listdir(root))
        rooms = [room for room in rooms if 'ply' in room]
        if split == 'train':
            self.file_list = rooms[:-3]    # + rooms[-1:]
        else:
            self.file_list = rooms[-3:-1]
        self.scene_points_list = []
        self.semantic_labels_list = []
        self.room_coord_min, self.room_coord_max = [], []
        for file in self.file_list:
            room_path = os.path.join(root, file)
            data = read_ply(room_path)
            points = np.vstack([data['x'], data['y'], data['z'], data['red'], data['green'], np.ones_like(data['red'])]).T
            self.scene_points_list.append(points)
            self.semantic_labels_list.append(data['class'])
            coord_min, coord_max = np.amin(points, axis=0)[:3], np.amax(points, axis=0)[:3]
            self.room_coord_min.append(coord_min), self.room_coord_max.append(coord_max)
        assert len(self.scene_points_list) == len(self.semantic_labels_list)

        labelweights = np.zeros(6 - len(self.ignore_labels))
        for seg in self.semantic_labels_list:
            tmp, _ = np.histogram(seg, range(7))
            self.scene_points_num.append(seg.shape[0])
            labelweights += [tmp[i] for i in range(len(tmp)) if i not in self.ignore_labels]
        labelweights = labelweights.astype(np.float32)
        labelweights = labelweights / np.sum(labelweights)
        self.labelweights = np.power(np.amax(labelweights) / labelweights, 1 / 3.0)

    def __getitem__(self, index):
        point_set_ini = self.scene_points_list[index]
        points = point_set_ini[:,:6]
        labels = self.semantic_labels_list[index]
        coord_min, coord_max = np.amin(points, axis=0)[:3], np.amax(points, axis=0)[:3]
        grid_x = int(np.ceil(float(coord_max[0] - coord_min[0] - self.block_size) / (self.stride * self.block_size)) + 1)
        grid_y = int(np.ceil(float(coord_max[1] - coord_min[1] - self.block_size) / (self.stride * self.block_size)) + 1)
        data_room, label_room, sample_weight, index_room = [], [], [], []
        for index_y in tqdm(range(0, grid_y), total=grid_y):
            for index_x in range(0, grid_x):
                s_x = coord_min[0] + index_x * (self.stride * self.block_size)
                e_x = min(s_x + self.block_size, coord_max[0])
                s_x = e_x - self.block_size
                s_y = coord_min[1] + index_y * (self.stride * self.block_size)
                e_y = min(s_y + self.block_size, coord_max[1])
                s_y = e_y - self.block_size
                point_idxs = np.where(
                    (points[:, 0] >= s_x - self.padding) & (points[:, 0] <= e_x + self.padding) & (points[:, 1] >= s_y - self.padding) & (
                                points[:, 1] <= e_y + self.padding))[0]
                if point_idxs.size == 0:
                    continue
                num_batch = int(np.ceil(point_idxs.size / self.block_points))
                point_size = int(num_batch * self.block_points)
                replace = False if (point_size - point_idxs.size <= point_idxs.size) else True
                point_idxs_repeat = np.random.choice(point_idxs, point_size - point_idxs.size, replace=replace)
                point_idxs = np.concatenate((point_idxs, point_idxs_repeat))
                np.random.shuffle(point_idxs)
                data_batch = points[point_idxs, :]
                normlized_xyz = np.zeros((point_size, 3))
                normlized_xyz[:, 0] = data_batch[:, 0] / coord_max[0]
                normlized_xyz[:, 1] = data_batch[:, 1] / coord_max[1]
                normlized_xyz[:, 2] = data_batch[:, 2] / coord_max[2]
                data_batch[:, 0] = data_batch[:, 0] - (s_x + self.block_size / 2.0)
                data_batch[:, 1] = data_batch[:, 1] - (s_y + self.block_size / 2.0)
                # data_batch[:, 3:6] /= 255.0
                data_batch = np.concatenate((data_batch, normlized_xyz), axis=1)
                label_batch = labels[point_idxs].astype(int)
                batch_weight = self.labelweights[label_batch - 1]

                # o(nlogn) -> o(n)
                data_room += [data_batch]
                label_room += [label_batch]
                sample_weight += [batch_weight]
                index_room += [point_idxs]

        data_room = np.vstack(data_room)
        label_room = np.hstack(label_room)
        sample_weight = np.hstack(sample_weight)
        index_room = np.hstack(index_room)

        data_room = data_room.reshape((-1, self.block_points, data_room.shape[1]))
        label_room = label_room.reshape((-1, self.block_points))
        sample_weight = sample_weight.reshape((-1, self.block_points))
        index_room = index_room.reshape((-1, self.block_points))
        return data_room, label_room, sample_weight, index_room

    def __len__(self):
        return len(self.scene_points_list)

if __name__ == '__main__':
    data_root = '/data/yxu/PointNonLocal/data/stanford_indoor3d/'
    num_point, test_area, block_size, sample_rate = 4096, 5, 1.0, 0.01

    point_data = DublinDataset(split='train', data_root=data_root, num_point=num_point, test_area=test_area, block_size=block_size, sample_rate=sample_rate, transform=None)
    print('point data size:', point_data.__len__())
    print('point data 0 shape:', point_data.__getitem__(0)[0].shape)
    print('point label 0 shape:', point_data.__getitem__(0)[1].shape)
    import torch, time, random
    manual_seed = 123
    random.seed(manual_seed)
    np.random.seed(manual_seed)
    torch.manual_seed(manual_seed)
    torch.cuda.manual_seed_all(manual_seed)
    def worker_init_fn(worker_id):
        random.seed(manual_seed + worker_id)
    train_loader = torch.utils.data.DataLoader(point_data, batch_size=16, shuffle=True, num_workers=16, pin_memory=True, worker_init_fn=worker_init_fn)
    for idx in range(4):
        end = time.time()
        for i, (input, target) in enumerate(train_loader):
            print('time: {}/{}--{}'.format(i+1, len(train_loader), time.time() - end))
            end = time.time()