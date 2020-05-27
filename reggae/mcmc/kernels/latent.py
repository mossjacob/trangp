import tensorflow as tf
from tensorflow_probability import distributions as tfd

from reggae.utilities import logit
from reggae.mcmc.kernels.mh import MetropolisKernel
from reggae.mcmc.kernels.wrappers import ESSWrapper
from reggae.models import GPKernelSelector
from reggae.utilities import jitter_cholesky, logit
from reggae.models.results import GenericResults

import numpy as np
f64 = np.float64


class LatentKernel(MetropolisKernel):
    def __init__(self, data,
                 likelihood, 
                 kernel_selector: GPKernelSelector, 
                 tf_mrna_present, 
                 state_indices, 
                 step_size,
                 sampling_method='joint'):
        self.fbar_prior_params = kernel_selector()
        self.kernel_priors = kernel_selector.priors()
        self.kernel_selector = kernel_selector
        self.num_tfs = data.f_obs.shape[1]
        self.num_genes = data.m_obs.shape[1]
        self.likelihood = likelihood
        self.tf_mrna_present = True
        self.state_indices = state_indices
        self.num_replicates = data.f_obs.shape[0]
        self.step_fn = self.f_one_step
        self.calc_prob_fn = self.f_calc_prob
        if sampling_method is 'joint':
            self.step_fn = self.joint_one_step
            self.calc_prob_fn = self.joint_calc_prob
            
        super().__init__(step_size, tune_every=50)

    def _one_step(self, current_state, previous_kernel_results, all_states):
        return self.step_fn(current_state, previous_kernel_results, all_states)

    def f_one_step(self, current_state, previous_kernel_results, all_states):
        old_probs = list()
        new_state = tf.identity(current_state)

        # MH
        kernel_params = (all_states[self.state_indices['kernel_params']][0], all_states[self.state_indices['kernel_params']][1])
        m, K = self.fbar_prior_params(*kernel_params)
        for r in range(self.num_replicates):
            # Gibbs step
            fbar = current_state[r]
            z_i = tfd.MultivariateNormalDiag(fbar, self.step_size).sample()
            fstar = tf.zeros_like(fbar)

            for i in range(self.num_tfs):
                invKsigmaK = tf.matmul(tf.linalg.inv(K[i]+tf.linalg.diag(self.step_size)), K[i]) # (C_i + hI)C_i
                L = jitter_cholesky(K[i]-tf.matmul(K[i], invKsigmaK))
                c_mu = tf.matmul(z_i[i, None], invKsigmaK)
                fstar_i = tf.matmul(tf.random.normal((1, L.shape[0]), dtype='float64'), L) + c_mu
                mask = np.zeros((self.num_tfs, 1), dtype='float64')
                mask[i] = 1
                fstar = (1-mask) * fstar + mask * fstar_i

            mask = np.zeros((self.num_replicates, 1, 1), dtype='float64')
            mask[r] = 1
            test_state = (1-mask) * new_state + mask * fstar

            new_prob = self.calc_prob_fn(test_state, all_states)
            old_prob = self.calc_prob_fn(new_state, all_states)
            #previous_kernel_results.target_log_prob #tf.reduce_sum(old_m_likelihood) + old_f_likelihood

            is_accepted = self.metropolis_is_accepted(new_prob, old_prob)
            
            prob = tf.cond(tf.equal(is_accepted, tf.constant(True)), lambda:new_prob, lambda:old_prob)


            new_state = tf.cond(tf.equal(is_accepted, tf.constant(False)),
                                lambda:new_state, lambda:test_state)

    def joint_one_step(self, current_state, previous_kernel_results, all_states):
        # Untransformed tf mRNA vectors F (Step 1)
        old_probs = list()
        new_state = tf.identity(current_state[0])
        new_params = []
        S = tf.linalg.diag(self.step_size)
        # MH
        m, K = self.fbar_prior_params(current_state[1], current_state[2])
        # Propose new params
        v = self.kernel_selector.proposal(0, current_state[1]).sample()
        l2 = self.kernel_selector.proposal(1, current_state[2]).sample()
        m_, K_ = self.fbar_prior_params(v, l2)

        for r in range(self.num_replicates):
            # Gibbs step
            fbar = new_state[r]
            z_i = tfd.MultivariateNormalDiag(fbar, self.step_size).sample()

            # Compute K_i(K_i + S)^-1 
            Ksuminv = tf.matmul(K, tf.linalg.inv(K+S))
            # Compute chol(K-K(K+S)^-1 K)
            L = jitter_cholesky(K-tf.matmul(Ksuminv, K))
            c_mu = tf.linalg.matvec(Ksuminv, z_i)
            # Compute nu = L^-1 (f-mu)
            invL = tf.linalg.inv(L)
            nu = tf.linalg.matvec(invL, fbar-c_mu)

            Ksuminv = tf.matmul(K_, tf.linalg.inv(K_+S)) 
            L = jitter_cholesky(K_-tf.matmul(K_, Ksuminv))
            c_mu = tf.linalg.matvec(Ksuminv, z_i)
            fstar = tf.linalg.matvec(L, nu) + c_mu

            mask = np.zeros((self.num_replicates, 1, 1), dtype='float64')
            mask[r] = 1
            test_state = (1-mask) * new_state + mask * fstar

            new_hyp = [v, l2]
            old_hyp = [current_state[1], current_state[2]]
            new_prob = self.calc_prob_fn(test_state, new_hyp, old_hyp, all_states)
            old_prob = self.calc_prob_fn(new_state, old_hyp, new_hyp, all_states)
            #previous_kernel_results.target_log_prob #tf.reduce_sum(old_m_likelihood) + old_f_likelihood

            is_accepted = self.metropolis_is_accepted(new_prob, old_prob)
            
            prob = tf.cond(tf.equal(is_accepted, tf.constant(True)), lambda:new_prob, lambda:old_prob)


            new_state = tf.cond(tf.equal(is_accepted, tf.constant(False)),
                                lambda:new_state, lambda:test_state)
            new_params = tf.cond(tf.equal(is_accepted, tf.constant(False)),
                                 lambda:[current_state[1], current_state[2]], lambda:[v, l2])

        return [new_state, *new_params], prob, is_accepted[0]
    
    def f_calc_prob(self, fstar, all_states):
        new_m_likelihood = self.likelihood.genes(
            all_states,
            self.state_indices,
            fbar=fstar,
        )
        new_f_likelihood = tf.cond(tf.equal(self.tf_mrna_present, tf.constant(True)), 
                                   lambda:tf.reduce_sum(self.likelihood.tfs(
                                       1e-6*tf.ones(self.num_tfs, dtype='float64'), # TODO
                                       fstar
                                   )), lambda:f64(0))
        new_prob = tf.reduce_sum(new_m_likelihood) + new_f_likelihood
        return new_prob

    def joint_calc_prob(self, fstar, new_hyp, old_hyp, all_states):
        new_m_likelihood = self.likelihood.genes(
            all_states,
            self.state_indices,
            fbar=fstar,
        )
        σ2_f = 1e-6*tf.ones(self.num_tfs, dtype='float64')
        if 'σ2_f' in self.state_indices:
            σ2_f = all_states[self.state_indices['σ2_f']]

        new_f_likelihood = tf.cond(tf.equal(self.tf_mrna_present, tf.constant(True)), 
                                   lambda:tf.reduce_sum(self.likelihood.tfs(
                                       σ2_f,
                                       fstar
                                   )), lambda:f64(0))
        new_prob = tf.reduce_sum(new_m_likelihood) + new_f_likelihood
        new_prob += tf.reduce_sum(
            self.kernel_priors[0].log_prob(new_hyp[0]) + \
            self.kernel_priors[1].log_prob(new_hyp[1])
        )
        new_prob += tf.reduce_sum(
            self.kernel_selector.proposal(0, new_hyp[0]).log_prob(old_hyp[0]) + \
            self.kernel_selector.proposal(1, new_hyp[1]).log_prob(old_hyp[1])
        )

        return new_prob

    def bootstrap_results(self, init_state, all_states):
        prob = self.calc_prob_fn(init_state[0], [init_state[1], init_state[2]], [init_state[1], init_state[2]], all_states)

        return GenericResults(prob, True)
    
    def is_calibrated(self):
        return True


class ESSBuilder:
    def __init__(self, data, state_indices, kernel_selector):
        self.state_indices = state_indices
        self.kernel_selector = kernel_selector
        self.num_replicates = data.f_obs.shape[0]
        self.num_tfs = data.f_obs.shape[1]

    def normal_sampler_fn_fn(self, all_states):
        def normal_sampler_fn(seed):
            p1, p2 = all_states[self.state_indices['kernel_params']]
            m, K = self.kernel_selector()(logit(p1), logit(p2))
            m = tf.zeros((self.num_replicates, self.num_tfs, self.N_p), dtype='float64')
            K = tf.stack([K for _ in range(3)], axis=0)
            # tf.print(p1, p2, K, m.shape)
            jitter = tf.linalg.diag(1e-8 *tf.ones(self.N_p, dtype='float64'))
            z = tfd.MultivariateNormalTriL(loc=m, 
                                scale_tril=tf.linalg.cholesky(K+jitter)).sample(seed=seed)
            # tf.print(z)
            return z
        return normal_sampler_fn

    def f_log_prob_fn(self, all_states):
        def f_log_prob(fstar):
            tf.print('here', fstar)
            # print(all_states)
            new_m_likelihood = self.likelihood.genes(
                all_states,
                self.state_indices,
                fbar=fstar,
            )
            σ2_f = 1e-6*tf.ones(self.num_tfs, dtype='float64')
            # if 'σ2_f' in self.state_indices:
            #     σ2_f = all_states[self.state_indices['σ2_f']]

            new_f_likelihood = tf.cond(tf.equal(self.options.tf_mrna_present, tf.constant(True)), 
                                    lambda:tf.reduce_sum(self.likelihood.tfs(
                                        σ2_f,
                                        fstar
                                    )), lambda:f64(0))
            return tf.reduce_sum(new_m_likelihood) + new_f_likelihood
        return f_log_prob
    latents_kernel = ESSWrapper(normal_sampler_fn_fn, f_log_prob_fn)
