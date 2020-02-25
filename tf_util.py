# Author: Wentao Yuan (wyuan1@cs.cmu.edu) 05/31/2018

import tensorflow as tf
from pc_distance import tf_nndistance, tf_approxmatch


def mlp(features, layer_dims, bn=None, bn_params=None):
    for i, num_outputs in enumerate(layer_dims[:-1]):
        features = tf.contrib.layers.fully_connected(
            features, num_outputs,
            normalizer_fn=bn,
            normalizer_params=bn_params,
            scope='fc_%d' % i)
    outputs = tf.contrib.layers.fully_connected(
        features, layer_dims[-1],
        activation_fn=None,
        scope='fc_%d' % (len(layer_dims) - 1))
    return outputs


def mlp_conv(inputs, layer_dims, bn=None, bn_params=None):
    for i, num_out_channel in enumerate(layer_dims[:-1]):
        inputs = tf.contrib.layers.conv1d(
            inputs, num_out_channel,
            kernel_size=1,
            normalizer_fn=bn,
            normalizer_params=bn_params,
            scope='conv_%d' % i)
    outputs = tf.contrib.layers.conv1d(
        inputs, layer_dims[-1],
        kernel_size=1,
        activation_fn=None,
        scope='conv_%d' % (len(layer_dims) - 1))
    return outputs

def mlp_conv_act(inputs, layer_dims, act_dim=11, bn=None, bn_params=None):
    for i, num_out_channel in enumerate(layer_dims[:-1]):
        inputs = tf.contrib.layers.conv1d(
            inputs, num_out_channel,
            kernel_size=1,
            normalizer_fn=bn,
            normalizer_params=bn_params,
            scope='conv_%d' % i)
    feature = tf.contrib.layers.conv1d(
        inputs, layer_dims[-1],
        kernel_size=1,
        activation_fn=None,
        scope='conv_%d' % (len(layer_dims) - 1))
    act = tf.contrib.layers.conv1d(
        inputs, act_dim,
        kernel_size=1,
        activation_fn=tf.math.sigmoid,
        scope='conv_act')
    outputs = tf.concat([feature, tf.nn.softmax(act)], axis=-1)
    return outputs

def point_maxpool(inputs, npts, keepdims=False):
    # outputs = [tf.transpose(tf.math.top_k(tf.transpose(f, perm=[0, 2, 1]), k=128).values, perm=[0, 2, 1])
    outputs = [tf.reduce_mean(tf.transpose(tf.math.top_k(tf.transpose(f, perm=[0, 2, 1]), k=32).values, perm=[0, 2, 1]), axis=1, keepdims=True)
        for f in tf.split(inputs, npts, axis=1)]
    """
    outputs = [tf.reduce_max(f, axis=1, keepdims=keepdims)
        for f in tf.split(inputs, npts, axis=1)]
    return tf.concat(outputs, axis=0)
    """
    if keepdims:
        return tf.concat(outputs, axis=0)
    else:
        return tf.squeeze(tf.concat(outputs, axis=0), axis=1)


def point_unpool(inputs, npts):
    inputs = tf.split(inputs, inputs.shape[0], axis=0)
    outputs = [tf.tile(f, [1, npts[i], 1]) for i,f in enumerate(inputs)]
    return tf.concat(outputs, axis=1)


def chamfer(pcd1, pcd2):
    dist1, _, dist2, _ = tf_nndistance.nn_distance(pcd1, pcd2)
    dist1 = tf.reduce_mean(tf.sqrt(dist1))
    dist2 = tf.reduce_mean(tf.sqrt(dist2))
    return (dist1 + dist2) / 2


def earth_mover(pcd1, pcd2):
    assert pcd1.shape[1] == pcd2.shape[1]
    num_points = tf.cast(pcd1.shape[1], tf.float32)
    match = tf_approxmatch.approx_match(pcd1, pcd2)
    cost = tf_approxmatch.match_cost(pcd1, pcd2, match)
    return tf.reduce_mean(cost / num_points)


def add_train_summary(name, value):
    tf.summary.scalar(name, value, collections=['train_summary'])


def add_valid_summary(name, value):
    avg, update = tf.metrics.mean(value)
    tf.summary.scalar(name, avg, collections=['valid_summary'])
    return update
