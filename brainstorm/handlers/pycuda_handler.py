#!/usr/bin/env python
# coding=utf-8
from __future__ import division, print_function, unicode_literals
import numpy as np
from pycuda import gpuarray, cumath
import pycuda.driver as drv
import pycuda.autoinit
from pycuda.elementwise import ElementwiseKernel
import scikits.cuda.linalg as culinalg
import scikits.cuda.misc as cumisc
culinalg.init()


class PyCudaHandler(object):
    def __init__(self):
        self.array_type = pycuda.gpuarray.GPUArray
        self.dtype = np.float32
        self.size = lambda x: x.size
        self.shape = lambda x: x.shape
        self.reshape = lambda x, s: x.reshape(s)
        self.slice = lambda x, s: x[s]
        self.context = cumisc._global_cublas_handle
        self.EMPTY = gpuarray.zeros((), dtype=self.dtype)

    def allocate(self, size):
        return gpuarray.zeros(size, dtype=self.dtype)

    @staticmethod
    def fill(mem, val):
        mem.fill(val)

    def set_from_numpy(self, mem, arr):
        assert mem.shape == arr.shape, "{} != {}".format(mem.shape, arr.shape)
        mem.set(arr.astype(self.dtype))

    def get_numpy_copy(self, mem):
        assert type(mem) == self.array_type
        return mem.get()

    @staticmethod
    def copy_to(dest, src):
        # Copy data from src to dest (both must be GPUArrays)
        drv.memcpy_dtod(dest.gpudata, src.gpudata, dest.nbytes)

    def zeros(self, shape):
        return gpuarray.zeros(shape=shape, dtype=self.dtype)

    def ones(self, shape):
        return gpuarray.ones(shape=shape, dtype=self.dtype)

    # ---------------- Mathematical Operations ---------------- #

    @staticmethod
    def sum_t(a, axis, out):
        cumisc.sum(a, axis, out)

    @staticmethod
    def dot_mm(a, b, out, transa='N', transb='N'):
        culinalg.dot(a, b, transa=transa, transb=transb, out=out)

    @staticmethod
    def dot_add_mm(a, b, out, transa='N', transb='N'):
        culinalg.add_dot(a, b, out, transa, transb)

    @staticmethod
    def elem_mult_tt(a, b, out):
        elem_mult_kernel(a, b, out)

    @staticmethod
    def elem_mult_st(a, b, out):
        elem_mult_st_kernel(a, b, out)

    @staticmethod
    def add_tt(a, b, out):
        add_mm_kernel(a, b, out)

    @staticmethod
    def subtract_tt(a, b, out):
        subtract_mm_kernel(a, b, out)

    @staticmethod
    def add_mv(a, b, out):
        cumisc.add_matvec(a, b, out=out)

    @staticmethod
    def broadcast_features_t(a, out):
        assert len(a.shape) == 3
        assert a.shape[2] == 1
        assert len(out.shape) > 2
        a_flat = a.reshape(-1)
        out_flat = out.reshape(-1)
        broadcast_features_kernel(out_flat, a_flat, np.prod(out.shape[2:]))

    @staticmethod
    def clip_t(a, a_min, a_max, out):
        clip_kernel(a, out, a_min, a_max)

    @staticmethod
    def log_t(a, out):
        cumath.log(a, out=out)

    @staticmethod
    def divide_tt(a, b, out):
        div_kernel(a, b, out)

    @staticmethod
    def divide_mv(m, v, out):
        """
        Divide (M, N) matrix elementwise by a (1, N) vector using broadcasting.
        """
        raise NotImplementedError()

    @staticmethod
    def mult_mv(m, v, out):
        """
        Multiply (M, N) matrix elementwise by a (1, N) vector using
        broadcasting.
        """
        raise NotImplementedError()

    @staticmethod
    def binarize_v(v, out):
        raise NotImplementedError()

    @staticmethod
    def index_m_by_v(m, v, out):
        raise NotImplementedError()

    # Activation functions

    @staticmethod
    def sigmoid(x, y):
        sigmoid_kernel(x, y)

    @staticmethod
    def sigmoid_deriv(x, y, dy, dx):
        sigmoid_deriv_kernel(x, y, dy, dx)

    @staticmethod
    def tanh(x, y):
        cumath.tanh(x, out=y)

    @staticmethod
    def tanh_deriv(x, y, dy, dx):
        tanh_deriv_kernel(x, y, dy, dx)

    @staticmethod
    def rel(x, y):
        rel_kernel(x, y)

    @staticmethod
    def rel_deriv(x, y, dy, dx):
        rel_deriv_kernel(x, y, dy, dx)

    @staticmethod
    def softmax_m(m, out):
        """Applies softmax to matrix over last dimension"""
        n, k = m.shape
        tmp = gpuarray.empty((1, n), dtype=m.dtype)
        __cuda_softmax_impl(m.gpudata, tmp.gpudata, out.gpudata, np.int32(n),
            np.int32(k), block=(32, 1, 1), grid=(n, 1, 1))
        return out


elem_mult_kernel = ElementwiseKernel(
    "float* x, float* y, float *out",
    "out[i] = x[i] * y[i]",
    "elem_mult_kernel"
)

elem_mult_st_kernel = ElementwiseKernel(
    "float x, float* y, float *out",
    "out[i] = x * y[i]",
    "elem_mult_kernel"
)

add_mm_kernel = ElementwiseKernel(
    "float* x, float* y, float *out",
    "out[i] = x[i] + y[i]",
    "add_mm_kernel"
)

subtract_mm_kernel = ElementwiseKernel(
    "float* x, float* y, float *out",
    "out[i] = x[i] - y[i]",
    "subtract_mm_kernel"
)

sigmoid_kernel = ElementwiseKernel(
    "float* x, float* y",
    "y[i] = 1.0/(1.0 + exp(-1*x[i])",
    "sigmoid_kernel"
)

sigmoid_deriv_kernel = ElementwiseKernel(
    "float* x, float* y, float* dy, float* dx",
    "dx[i] = dy[i] * y[i] * (1.0 - y[i])",
    "sigmoid_deriv_kernel"
)

tanh_deriv_kernel = ElementwiseKernel(
    "float* x, float* y, float* dy, float* dx",
    "dx[i] = dy[i] * (1.0 - y[i] * y[i])",
    "tanh_deriv_kernel"
)

rel_kernel = ElementwiseKernel(
    "float* x, float* y",
    "if (x[i]>0) y[i] = x[i]; else y[i]=0.0;",
    "rel_kernel"
)

rel_deriv_kernel = ElementwiseKernel(
    "float* x, float* y, float* dy, float* dx",
    "if (x[i]>0) dx[i] = dy[i]; else dx[i]=0.0;",
    "rel_deriv_kernel"
)

broadcast_features_kernel = ElementwiseKernel(
    "float* out, float* a, unsigned int broadcast_size",
    "out[i] = a[i / broadcast_size]",
    "bc_features_kernel"
)

clip_kernel = ElementwiseKernel(
    "float* a, float* out, float a_min, float a_max",
    "out[i] = fminf(fmaxf(a[i], a_min), a_max);",
    "clip_kernel"
)

div_kernel = ElementwiseKernel(
    "float* a, float* b, float* out",
    "out[i] = a[i] / b[i];",
    "div_kernel"
)


__softmax_kernel_code = """
    __global__ void softmax_kernel(float* mat, float* tmp, float* out,
                                   unsigned int height, unsigned int width) {
          __shared__ float max_vals[32];
        float cur_max = -FLT_MAX;
        float val = 0;

        for (unsigned int i = threadIdx.x; i < width; i += 32) {
            val = mat[blockIdx.x * width + i];
            if (val > cur_max)
                cur_max = val;
        }

        max_vals[threadIdx.x] = cur_max;
        __syncthreads();
        if (threadIdx.x == 0) {
            cur_max = -FLT_MAX;
            for (unsigned int i = 0; i < 32; i++) {
                if (max_vals[i] > cur_max)
                    cur_max = max_vals[i];
            }
            tmp[blockIdx.x] = cur_max;
        }
        __syncthreads();


        float sum = 0.0;
        for (unsigned int i = threadIdx.x; i < width; i += 32) {
            float x =  __expf(mat[blockIdx.x * width + i] - tmp[blockIdx.x]);
            out[blockIdx.x * width + i] = x;
            sum += x;
        }
        max_vals[threadIdx.x] = sum;
        __syncthreads();
        if (threadIdx.x == 0) {
            sum = 0.0;
            for (unsigned int i = 0; i < 32; i++)
                sum += max_vals[i];
            tmp[blockIdx.x] = sum;
        }
        __syncthreads();
        for (unsigned int i = threadIdx.x; i < width; i += 32) {
            out[blockIdx.x * width + i] /= tmp[blockIdx.x];
        }
    }
    """
    mod = SourceModule(__softmax_kernel_code)
    _softmax_impl = mod.get_function("softmax_kernel")
