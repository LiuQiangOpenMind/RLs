import gym
import threading
import numpy as np
from gym.spaces import Box, Discrete, Tuple
from .wrappers import SkipEnv, StackEnv, GrayResizeEnv, ScaleEnv, OneHotObsEnv, BoxActEnv, BaseEnv


class FakeMultiThread(threading.Thread):

    def __init__(self, func, args=()):
        super().__init__()
        self.func = func
        self.args = args

    def run(self):
        self.result = self.func(*self.args)

    def get_result(self):
        try:
            return self.result
        except Exception:
            return None


class gym_envs(object):

    def __init__(self, gym_env_name, n, seed=0, render_mode='first', **kwargs):
        '''
        Input:
            gym_env_name: gym training environment id, i.e. CartPole-v0
            n: environment number
            render_mode: mode of rendering, optional: first, last, all, random_[num] -> i.e. random_2, [list] -> i.e. [0, 2, 4]
        '''
        _skip = bool(kwargs.get('skip', False))
        _stack = bool(kwargs.get('stack', False))
        _grayscale = bool(kwargs.get('grayscale', False))
        _resize = bool(kwargs.get('resize', False))
        _scale = bool(kwargs.get('scale', False))
        env_params = {
            'gym_env_name': gym_env_name,
            'skip': _skip,
            'stack': _stack,
            'grayscale': _grayscale,
            'resize': _resize,
            'scale': _scale,
        }

        def get_env(gym_env_name, skip=False, stack=False, grayscale=False, resize=False, scale=False):
            env = gym.make(gym_env_name)
            env = BaseEnv(env)
            if skip:
                env = SkipEnv(env)
            if isinstance(env.observation_space, Box):
                if len(env.observation_space.shape) == 3:
                    if grayscale or resize:
                        env = GrayResizeEnv(env, resize=resize, grayscale=grayscale)
                    if scale:
                        env = ScaleEnv(env)
                if stack:
                    env = StackEnv(env)
            else:
                env = OneHotObsEnv(env)

            if isinstance(env.action_space, Box) and len(env.action_space.shape) == 1:
                env = BoxActEnv(env)
            return env

        self.n = n  # environments number
        self._initialize(
            env=get_env(**env_params)
        )
        self.envs = [
            get_env(**env_params)
            for _ in range(self.n)]
        self.seeds = [seed + i for i in range(n)]
        [env.seed(s) for env, s in zip(self.envs, self.seeds)]
        self._get_render_index(render_mode)

    def _initialize(self, env):
        assert isinstance(env.observation_space, (Box, Discrete)) and isinstance(env.action_space, (Box, Discrete)), 'action_space and observation_space must be one of available_type'
        # process observation
        ObsSpace = env.observation_space
        if isinstance(ObsSpace, Box):
            self.s_dim = ObsSpace.shape[0] if len(ObsSpace.shape) == 1 else 0
            self.obs_high = ObsSpace.high
            self.obs_low = ObsSpace.low
        else:
            self.s_dim = int(ObsSpace.n)
        if len(ObsSpace.shape) == 3:
            self.obs_type = 'visual'
            self.visual_sources = 1
            self.visual_resolution = list(ObsSpace.shape)
        else:
            self.obs_type = 'vector'
            self.visual_sources = 0
            self.visual_resolution = []

        # process action
        ActSpace = env.action_space
        if isinstance(ActSpace, Box):
            assert len(ActSpace.shape) == 1, 'if action space is continuous, the shape length of action must equal to 1'
            self.action_type = 'continuous'
            self._is_continuous = True
            self.a_dim_or_list = ActSpace.shape
        elif isinstance(ActSpace, Tuple):
            assert all([isinstance(i, Discrete) for i in ActSpace]) == True, 'if action space is Tuple, each item in it must have type Discrete'
            self.action_type = 'Tuple(Discrete)'
            self._is_continuous = False
            self.a_dim_or_list = [i.n for i in ActSpace]
        else:
            self.action_type = 'discrete'
            self._is_continuous = False
            self.a_dim_or_list = [env.action_space.n]

        self.reward_threshold = env.env.spec.reward_threshold  # reward threshold refer to solved
        env.close()

    @property
    def is_continuous(self):
        return self._is_continuous

    def _get_render_index(self, render_mode):
        '''
        get render windows list, i.e. [0, 1] when there are 4 training enviornment.
        '''
        assert isinstance(render_mode, (list, str)), 'render_mode must have type of str or list.'
        if isinstance(render_mode, list):
            assert all([isinstance(i, int) for i in render_mode]), 'items in render list must have type of int'
            assert min(index) >= 0, 'index must larger than zero'
            assert max(index) <= self.n, 'render index cannot larger than environment number.'
            self.render_index = render_mode
        elif isinstance(render_mode, str):
            if render_mode == 'first':
                self.render_index = [0]
            elif render_mode == 'last':
                self.render_index = [-1]
            elif render_mode == 'all':
                self.render_index = [i for i in range(self.n)]
            else:
                a, b = render_mode.split('_')
                if a == 'random' and 0 < int(b) <= self.n:
                    import random
                    self.render_index = random.sample([i for i in range(self.n)], int(b))
        else:
            raise Exception('render_mode must be first, last, all, [list] or random_[num]')

    def render(self):
        '''
        render game windows.
        '''
        [self.envs[i].render() for i in self.render_index]

    def close(self):
        '''
        close all environments.
        '''
        [env.close() for env in self.envs]

    def sample_actions(self):
        '''
        generate random actions for all training environment.
        '''
        return np.asarray([env.action_sample() for env in self.envs])

    def reset(self):
        self.dones_index = []
        threadpool = []
        for i in range(self.n):
            th = FakeMultiThread(self.envs[i].reset, args=())
            threadpool.append(th)
        for th in threadpool:
            th.start()
        for th in threadpool:
            threading.Thread.join(th)
        obs = np.asarray([threadpool[i].get_result() for i in range(self.n)])
        return obs

    def step(self, actions):
        if self.action_type == 'discrete':
            actions = actions.reshape(-1,)
        elif self.action_type == 'Tuple(Discrete)':
            actions = actions.reshape(self.n, -1).tolist()
        threadpool = []
        for i in range(self.n):
            th = FakeMultiThread(self.envs[i].step, args=(actions[i], ))
            threadpool.append(th)
        for th in threadpool:
            th.start()
        for th in threadpool:
            threading.Thread.join(th)
        results = [threadpool[i].get_result() for i in range(self.n)]

        obs, reward, done, info = [np.asarray(e) for e in zip(*results)]
        self.dones_index = np.where(done)[0]
        return obs, reward, done, info

    def partial_reset(self):
        threadpool = []
        for i in self.dones_index:
            th = FakeMultiThread(self.envs[i].reset, args=())
            threadpool.append(th)
        for th in threadpool:
            th.start()
        for th in threadpool:
            threading.Thread.join(th)
        obs = np.asarray([threadpool[i].get_result() for i in range(self.dones_index.shape[0])])
        return obs
