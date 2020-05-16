import numpy as np
from tensorflow import math as tfm
import tensorflow as tf
from tensorflow import linalg
from tensorflow_probability import distributions as tfd

f64 = np.float64

def discretise(t, num_disc = 10):
    gcd = np.gcd.reduce(t)
    t_augmented = np.arange(0, t[-1]+gcd, gcd)
    N = t_augmented.shape[0]
    
    def calc_N_p(N_p, num_disc):
        '''A helper function to ensure t is a subset of τ'''
        return (N_p-1)*(num_disc+1)+1
    N_p = calc_N_p(N, num_disc)  # Number of time discretisations
    τ = np.linspace(0, t_augmented[-1], N_p, dtype='float64')    # Discretised observation times
    i = int(t[0]/gcd)
    τ = τ[i*num_disc+i:]
    common_indices = np.searchsorted(τ, t)
    return τ, common_indices

def get_time_square(times, N):
    t_1 = tf.transpose(tf.reshape(tf.tile(times, [N]), [N, N]))
    t_2 = tf.reshape(tf.tile(times, [N]), [N, N])
    return t_1, t_2

def logistic(x): # (inverse logit)
    return tfm.exp(x)/(1+tfm.exp(x))

def logit(x, nan_replace=0):
    # print(x>1)
    # if reduce_any(x>1):
    #     return np.inf * ones(x.shape, dtype='float64')
    x = tfm.log(x/(1-x))
    
    x = tf.where(
        tf.math.is_nan(x),
        nan_replace*tf.ones([], x.dtype),
        x)

    return x

def exp(x):
    '''Safe exp'''
    with np.errstate(under='ignore', over='ignore'):
        return np.exp(x)
    
def mult(a, b):
    '''Safe multiplication'''
    with np.errstate(under='ignore', over='ignore', invalid='ignore'):
        c = a*b
        return np.where(np.isnan(c), 0, c)

def jitter_cholesky(A):
    try:
        jitter1 = linalg.diag(1e-7 * np.ones(A.shape[0]))
        return linalg.cholesky(A + jitter1)
    except:
        jitter2 = linalg.diag(1e-5 * np.ones(A.shape[0]))
        return linalg.cholesky(A + jitter2)

class ArrayList:
    def __init__(self, shape):
        self.capacity = 100
        self.shape = shape
        self.data = np.zeros((self.capacity, *shape))
        self.size = 0

    def add(self, x):
        if self.size == self.capacity:
            self.capacity *= 4
            newdata = np.zeros((self.capacity, *self.shape))
            newdata[:self.size] = self.data
            self.data = newdata

        self.data[self.size] = x
        self.size += 1

    def get(self):
        data = self.data[:self.size]
        return data

class LogisticNormal():
    def __init__(self, a, b, loc=f64(0), scale=f64(1.78), allow_nan_stats=True):
        self.a = a
        self.b = b
        self.dist = tfd.LogitNormal(loc, scale, allow_nan_stats=allow_nan_stats)
#         super().__init__(loc, scale, allow_nan_stats=allow_nan_stats)
    def log_prob(self, x):
        x = (x-self.a)/(self.b-self.a)
        log_prob = self.dist.log_prob(x)
        log_prob = tf.where(
            tf.math.is_nan(log_prob),
            -1e2*tf.ones([], log_prob.dtype),
            log_prob)

        return log_prob

def rotate(matrix, shifts):
    """"requested rotate function - assumes matrix shape is mxn and shifts shape is m"""

    # get shape of the input matrix
    shape = tf.shape(matrix)

    # compute and stack the meshgrid to get the index matrix of shape (2,m,n)
    ind = tf.stack(tf.meshgrid(tf.range(shape[0]), tf.range(shape[1]), indexing='ij'))
    # reshape it to (m,n,2)
    ind = tf.transpose(ind, [1,2,0])

    # add the value from shifts to the corresponding row and devide modulo shape[1]
    # this will effectively introduce the desired shift, but at the level of indices
    shifted_ind = tfm.mod(tf.transpose(tf.transpose(ind[:,:,1]) + shifts), shape[1])

    # convert the shifted indices to the right shape
    new_ind = tf.transpose(tf.stack([ind[:,:,0], shifted_ind]) , [1,2,0]) 

    # return the resliced tensor
    return tf.gather_nd(matrix, new_ind)
