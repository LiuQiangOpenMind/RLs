import Nn
import numpy as np
import tensorflow as tf
import tensorflow_probability as tfp
from Algorithms.tf2algos.base.off_policy import Off_Policy


class DDPG(Off_Policy):
    '''
    Deep Deterministic Policy Gradient, https://arxiv.org/abs/1509.02971
    '''
    def __init__(self,
                 s_dim,
                 visual_sources,
                 visual_resolution,
                 a_dim_or_list,
                 is_continuous,

                 ployak=0.995,
                 actor_lr=5.0e-4,
                 critic_lr=1.0e-3,
                 discrete_tau=1.0,
                 hidden_units={
                     'actor_continuous': [32, 32],
                     'actor_discrete': [32, 32],
                     'q': [32, 32]
                 },
                 **kwargs):
        super().__init__(
            s_dim=s_dim,
            visual_sources=visual_sources,
            visual_resolution=visual_resolution,
            a_dim_or_list=a_dim_or_list,
            is_continuous=is_continuous,
            **kwargs)
        self.ployak = ployak
        self.discrete_tau = discrete_tau

        if self.is_continuous:
            _actor_net = lambda: Nn.actor_dpg(self.rnn_net.hdim, self.a_counts, hidden_units['actor_continuous'])
            # self.action_noise = Nn.NormalActionNoise(mu=np.zeros(self.a_counts), sigma=1 * np.ones(self.a_counts))
            self.action_noise = Nn.OrnsteinUhlenbeckActionNoise(mu=np.zeros(self.a_counts), sigma=0.2 * np.exp(-self.episode / 10) * np.ones(self.a_counts))
        else:
            _actor_net = lambda: Nn.actor_discrete(self.rnn_net.hdim, self.a_counts, hidden_units['actor_discrete'])
            self.gumbel_dist = tfp.distributions.Gumbel(0, 1)

        self.actor_net = _actor_net()
        self.actor_target_net = _actor_net()
        self.actor_tv = self.actor_net.trainable_variables
        
        _q_net = lambda : Nn.critic_q_one(self.rnn_net.hdim, self.a_counts, hidden_units['q'])
        self.q_net = _q_net()
        self.q_target_net = _q_net()
        self.critic_tv = self.q_net.trainable_variables + self.other_tv
        self.update_target_net_weights(
            self.actor_target_net.weights + self.q_target_net.weights,
            self.actor_net.weights + self.q_net.weights
        )
        self.actor_lr = tf.keras.optimizers.schedules.PolynomialDecay(actor_lr, self.max_episode, 1e-10, power=1.0)
        self.critic_lr = tf.keras.optimizers.schedules.PolynomialDecay(critic_lr, self.max_episode, 1e-10, power=1.0)
        self.optimizer_actor = tf.keras.optimizers.Adam(learning_rate=self.actor_lr(self.episode))
        self.optimizer_critic = tf.keras.optimizers.Adam(learning_rate=self.critic_lr(self.episode))

        self.model_recorder(dict(
            actor=self.actor_net,
            critic=self.q_net,
            optimizer_actor=self.optimizer_actor,
            optimizer_critic=self.optimizer_critic
        ))

    def show_logo(self):
        self.recorder.logger.info('''
　　　ｘｘｘｘｘｘｘ　　　　　　　　ｘｘｘｘｘｘｘ　　　　　　　　ｘｘｘｘｘｘｘｘ　　　　　　　　ｘｘｘｘｘｘ　　　　　
　　　　　ｘ　　ｘｘｘ　　　　　　　　　ｘ　　ｘｘｘ　　　　　　　　　ｘｘ　　ｘｘ　　　　　　　ｘｘｘ　　ｘｘ　　　　　
　　　　　ｘ　　　ｘｘ　　　　　　　　　ｘ　　　ｘｘ　　　　　　　　　ｘ　　　ｘｘｘ　　　　　　ｘｘ　　　　ｘ　　　　　
　　　　　ｘ　　　ｘｘ　　　　　　　　　ｘ　　　ｘｘ　　　　　　　　　ｘ　　　ｘｘｘ　　　　　　ｘｘ　　　　　　　　　　
　　　　　ｘ　　　ｘｘｘ　　　　　　　　ｘ　　　ｘｘｘ　　　　　　　　ｘｘｘｘｘｘ　　　　　　　ｘ　　　ｘｘｘｘｘ　　　
　　　　　ｘ　　　ｘｘ　　　　　　　　　ｘ　　　ｘｘ　　　　　　　　　ｘ　　　　　　　　　　　　ｘｘ　　　ｘｘｘ　　　　
　　　　　ｘ　　　ｘｘ　　　　　　　　　ｘ　　　ｘｘ　　　　　　　　　ｘ　　　　　　　　　　　　ｘｘ　　　　ｘ　　　　　
　　　　　ｘ　　ｘｘｘ　　　　　　　　　ｘ　　ｘｘｘ　　　　　　　　　ｘ　　　　　　　　　　　　ｘｘｘ　　ｘｘ　　　　　
　　　ｘｘｘｘｘｘｘ　　　　　　　　ｘｘｘｘｘｘｘ　　　　　　　　ｘｘｘｘｘ　　　　　　　　　　　ｘｘｘｘｘｘ　　　　　
　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　　ｘｘ　　　　　
        ''')

    def choose_action(self, s, visual_s, evaluation=False):
        mu, pi, self.cell_state = self._get_action(s, visual_s, self.cell_state)
        a = mu.numpy() if evaluation else pi.numpy()
        return a

    @tf.function
    def _get_action(self, s, visual_s, cell_state):
        with tf.device(self.device):
            feat, cell_state = self.get_feature(s, visual_s, cell_state=cell_state, record_cs=True, train=False)
            if self.is_continuous:
                mu = self.actor_net(feat)
                pi = tf.clip_by_value(mu + self.action_noise(), -1, 1)
            else:
                logits = self.actor_net(feat)
                mu = tf.argmax(logits, axis=1)
                cate_dist = tfp.distributions.Categorical(logits)
                pi = cate_dist.sample()
            return mu, pi, cell_state

    def learn(self, **kwargs):
        self.episode = kwargs['episode']
        for i in range(kwargs['step']):
            self._learn(function_dict={
                'train_function': self.train,
                'update_function': lambda : self.update_target_net_weights(
                                            self.actor_target_net.weights + self.q_target_net.weights,
                                            self.actor_net.weights + self.q_net.weights,
                                            self.ployak),
                'summary_dict': dict([
                                    ['LEARNING_RATE/actor_lr', self.actor_lr(self.episode)],
                                    ['LEARNING_RATE/critic_lr', self.critic_lr(self.episode)]
                                ])
            })

    @tf.function(experimental_relax_shapes=True)
    def train(self, memories, isw, crsty_loss, cell_state):
        ss, vvss, a, r, done = memories
        batch_size = tf.shape(a)[0]
        with tf.device(self.device):
            with tf.GradientTape() as tape:
                feat, feat_ = self.get_feature(ss, vvss, cell_state=cell_state, s_and_s_=True)
                if self.is_continuous:
                    target_mu = self.actor_target_net(feat_)
                    action_target = tf.clip_by_value(target_mu + self.action_noise(), -1, 1)
                else:
                    target_logits = self.actor_target_net(feat_)
                    target_cate_dist = tfp.distributions.Categorical(target_logits)
                    target_pi = target_cate_dist.sample()
                    action_target = tf.one_hot(target_pi, self.a_counts, dtype=tf.float32)
                q = self.q_net(feat, a)
                q_target = self.q_target_net(feat_, action_target)
                dc_r = tf.stop_gradient(r + self.gamma * q_target * (1 - done))
                td_error = q - dc_r
                q_loss = 0.5 * tf.reduce_mean(tf.square(td_error) * isw) + crsty_loss
            q_grads = tape.gradient(q_loss, self.critic_tv)
            self.optimizer_critic.apply_gradients(
                zip(q_grads, self.critic_tv)
            )
            with tf.GradientTape() as tape:
                if self.is_continuous:
                    mu = self.actor_net(feat)
                    pi = tf.clip_by_value(mu + self.action_noise(), -1, 1)
                else:
                    logits = self.actor_net(feat)
                    logp_all = tf.nn.log_softmax(logits)
                    gumbel_noise = tf.cast(self.gumbel_dist.sample([batch_size, self.a_counts]), dtype=tf.float32)
                    _pi = tf.nn.softmax((logp_all + gumbel_noise) / self.discrete_tau)
                    _pi_true_one_hot = tf.one_hot(tf.argmax(_pi, axis=-1), self.a_counts)
                    _pi_diff = tf.stop_gradient(_pi_true_one_hot - _pi)
                    pi = _pi_diff + _pi
                q_actor = self.q_net(feat, pi)
                actor_loss = -tf.reduce_mean(q_actor)
            actor_grads = tape.gradient(actor_loss, self.actor_tv)
            self.optimizer_actor.apply_gradients(
                zip(actor_grads, self.actor_tv)
            )
            self.global_step.assign_add(1)
            return td_error, dict([
                ['LOSS/actor_loss', actor_loss],
                ['LOSS/critic_loss', q_loss],
                ['Statistics/q_min', tf.reduce_min(q)],
                ['Statistics/q_mean', tf.reduce_mean(q)],
                ['Statistics/q_max', tf.reduce_max(q)]
            ])

    @tf.function(experimental_relax_shapes=True)
    def train_persistent(self, memories, isw, crsty_loss, cell_state):
        ss, vvss, a, r, done = memories
        batch_size = tf.shape(a)[0]
        with tf.device(self.device):
            with tf.GradientTape(persistent=True) as tape:
                feat, feat_ = self.get_feature(ss, vvss, cell_state=cell_state, s_and_s_=True)
                if self.is_continuous:
                    target_mu = self.actor_target_net(feat_)
                    action_target = tf.clip_by_value(target_mu + self.action_noise(), -1, 1)
                    mu = self.actor_net(feat)
                    pi = tf.clip_by_value(mu + self.action_noise(), -1, 1)
                else:
                    target_logits = self.actor_target_net(feat_)
                    target_cate_dist = tfp.distributions.Categorical(target_logits)
                    target_pi = target_cate_dist.sample()
                    action_target = tf.one_hot(target_pi, self.a_counts, dtype=tf.float32)
                    logits = self.actor_net(feat)
                    logp_all = tf.nn.log_softmax(logits)
                    gumbel_noise = tf.cast(self.gumbel_dist.sample([batch_size, self.a_counts]), dtype=tf.float32)
                    _pi = tf.nn.softmax((logp_all + gumbel_noise) / self.discrete_tau)
                    _pi_true_one_hot = tf.one_hot(tf.argmax(_pi, axis=-1), self.a_counts)
                    _pi_diff = tf.stop_gradient(_pi_true_one_hot - _pi)
                    pi = _pi_diff + _pi
                q = self.q_net(feat, a)
                q_target = self.q_target_net(feat_, action_target)
                dc_r = tf.stop_gradient(r + self.gamma * q_target * (1 - done))
                td_error = q - dc_r
                q_loss = 0.5 * tf.reduce_mean(tf.square(td_error) * isw) + crsty_loss

                q_actor = self.q_net(feat, pi)
                actor_loss = -tf.reduce_mean(q_actor)
            q_grads = tape.gradient(q_loss, self.critic_tv)
            self.optimizer_critic.apply_gradients(
                zip(q_grads, self.critic_tv)
            )
            actor_grads = tape.gradient(actor_loss, self.actor_tv)
            self.optimizer_actor.apply_gradients(
                zip(actor_grads, self.actor_tv)
            )
            self.global_step.assign_add(1)
            return td_error, dict([
                ['LOSS/actor_loss', actor_loss],
                ['LOSS/critic_loss', q_loss],
                ['Statistics/q_min', tf.reduce_min(q)],
                ['Statistics/q_mean', tf.reduce_mean(q)],
                ['Statistics/q_max', tf.reduce_max(q)]
            ])
