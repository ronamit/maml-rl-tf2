import json

import numpy as np
import tensorflow as tf

from maml_rl.baselines import LinearFeatureBaseline
from maml_rl.metalearners import MetaLearner
from maml_rl.policies import CategoricalMLPPolicy, NormalMLPPolicy
from maml_rl.optimizers import ConjugateGradientOptimizer
from maml_rl.sampler import BatchSampler


def total_rewards(episodes_rewards, aggregation=tf.reduce_mean):
    rewards = tf.math.reduce_mean(tf.stack([aggregation(tf.reduce_sum(rewards, axis=0))
                                            for rewards in episodes_rewards], axis=0))
    assert tf.rank(rewards) == 0
    return rewards


def main(args):
    continuous_actions = (args.env_name in ['AntVel-v1',  'AntDir-v1',
                                            'AntPos-v0', 'HalfCheetahVel-v1',
                                            'HalfCheetahDir-v1', '2DNavigation-v0'])

    writer = tf.summary.create_file_writer('./logs/{0}'.format(args.output_folder))

    save_folder = './saves/{0}'.format(args.output_folder)
    if not os.path.exists(save_folder):
        os.makedirs(save_folder)
    with open(os.path.join(save_folder, 'config.json'), 'w') as f:
        config = {k: v for (k, v) in vars(args).items() if k != 'device'}
        config.update(device=args.device)
        json.dump(config, f, indent=2)

    sampler = BatchSampler(args.env_name,
                           batch_size=args.fast_batch_size,
                           num_workers=args.num_workers)

    # Create policy for the given task
    with tf.name_scope('policy') as scope:
        if continuous_actions:
            policy = NormalMLPPolicy(
                int(np.prod(sampler.envs.observation_space.shape)),
                int(np.prod(sampler.envs.action_space.shape)),
                hidden_sizes=(args.hidden_size,) * args.num_layers,
                name=scope
            )
        else:
            policy = CategoricalMLPPolicy(
                int(np.prod(sampler.envs.observation_space.shape)),
                sampler.envs.action_space.n,
                hidden_sizes=(args.hidden_size,) * args.num_layers,
                name=scope
            )

    baseline = LinearFeatureBaseline(int(np.prod(sampler.envs.observation_space.shape)))

    optimizer = ConjugateGradientOptimizer(args.cg_damping,
                                           args.cg_iters,
                                           args.ls_backtrack_ratio,
                                           args.ls_max_steps,
                                           args.max_kl,
                                           policy)

    metalearner = MetaLearner(sampler,
                              policy,
                              baseline,
                              optimizer=optimizer,
                              gamma=args.gamma,
                              fast_lr=args.fast_lr,
                              tau=args.tau)

    optimizer.setup(metalearner)

    for batch in range(args.num_batches):
        print(f"----------Batch number {batch+1}----------")
        tasks = sampler.sample_tasks(num_tasks=args.meta_batch_size)
        episodes = metalearner.sample(tasks,
                                      first_order=args.first_order)
        metalearner.step(episodes)

        with writer.as_default():
            return_before = total_rewards([ep.rewards for ep, _ in episodes])
            return_after = total_rewards([ep.rewards for _, ep in episodes])
            tf.summary.scalar('total_rewards/before_update', return_before, batch)
            tf.summary.scalar('total_rewards/after_update', return_after, batch)
            print(f"{batch+1}:: \t Before: {return_before} \t After: {return_after}")
            writer.flush()

        if (batch+1) % args.save_iters == 0:
            # Save policy network
            policy.save_weights(save_folder + f"/policy-{batch+1}", overwrite=True)
            baseline.save_weights(save_folder + f"/baseline-{batch + 1}", overwrite=True)
            print(f"Policy saved at iteration {batch+1}")


if __name__ == '__main__':
    import argparse
    import os
    import multiprocessing as mp

    parser = argparse.ArgumentParser(description='Reinforcement learning with '
                                                 'Model-Agnostic Meta-Learning (MAML)')

    # General
    parser.add_argument('--env-name', type=str,
                        help='name of the environment')
    parser.add_argument('--gamma', type=float, default=0.95,
                        help='value of the discount factor gamma')
    parser.add_argument('--tau', type=float, default=1.0,
                        help='value of the discount factor for GAE')
    parser.add_argument('--first-order', action='store_true',
                        help='use the first-order approximation of MAML')

    # Policy network (relu activation function)
    parser.add_argument('--hidden-size', type=int, default=100,
                        help='number of hidden units per layer')
    parser.add_argument('--num-layers', type=int, default=2,
                        help='number of hidden layers')

    # Task-specific
    parser.add_argument('--fast-batch-size', type=int, default=20,
                        help='batch size for each individual task')
    parser.add_argument('--fast-lr', type=float, default=0.5,
                        help='learning rate for the 1-step gradient update of MAML')

    # Optimization
    parser.add_argument('--num-batches', type=int, default=200,
                        help='number of batches')
    parser.add_argument('--meta-batch-size', type=int, default=40,
                        help='number of tasks per batch')
    parser.add_argument('--max-kl', type=float, default=1e-2,
                        help='maximum value for the KL constraint in TRPO')
    parser.add_argument('--cg-iters', type=int, default=10,
                        help='number of iterations of conjugate gradient')
    parser.add_argument('--cg-damping', type=float, default=1e-5,
                        help='damping in conjugate gradient')
    parser.add_argument('--ls-max-steps', type=int, default=15,
                        help='maximum number of iterations for line search')
    parser.add_argument('--ls-backtrack-ratio', type=float, default=0.8,
                        help='maximum number of iterations for line search')

    # Miscellaneous
    parser.add_argument('--output-folder', type=str, default='maml',
                        help='name of the output folder')
    parser.add_argument('--num-workers', type=int, default=mp.cpu_count() - 1,
                        help='number of workers for trajectories sampling')
    parser.add_argument('--save-iters', type=int, default=10,
                        help='Number of iterations to pass so that the policy will be saved')
    parser.add_argument('--device', type=str, default='cpu',
                        help='set the device (cpu or cuda)')

    args = parser.parse_args()

    # Create logs and saves folder if they don't exist
    if not os.path.exists('./logs'):
        os.makedirs('./logs')
    if not os.path.exists('./saves'):
        os.makedirs('./saves')

    main(args)
