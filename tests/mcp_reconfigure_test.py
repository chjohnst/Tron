"""Tests for reconfiguring mcp."""
import tempfile

import yaml
from testify import TestCase, run, setup, assert_equal, teardown, suite

from tests.assertions import assert_length
from tron import mcp, event
from tron.config import config_parse
from tron.serialize import filehandler

class MCPReconfigureTestCase(TestCase):

    pre_config = dict(
        ssh_options=dict(
            agent=True,
            identities=['tests/test_id_rsa'],
        ),
        nodes=[
            dict(name='node0', hostname='batch0'),
            dict(name='node1', hostname='batch1'),
        ],
        node_pools=[dict(name='nodePool', nodes=['node0', 'node1'])],
        command_context={
            'thischanges': 'froma'
        },
        jobs=[
            dict(
                name='test_unchanged',
                node='node0',
                schedule='daily',
                actions=[dict(name='action_unchanged',
                              command='command_unchanged') ]
            ),
            dict(
                name='test_remove',
                node='node1',
                schedule=dict(interval='20s'),
                actions=[dict(name='action_remove',
                              command='command_remove')],
                cleanup_action=dict(name='cleanup', command='doit')
            ),
            dict(
                name='test_change',
                node='nodePool',
                schedule=dict(interval='20s'),
                actions=[
                    dict(name='action_change',
                         command='command_change'),
                    dict(name='action_remove2',
                         command='command_remove2',
                         requires=['action_change']),
                ],
            ),
            dict(
                name='test_daily_change',
                node='node0',
                schedule='daily',
                        actions=[dict(name='action_daily_change',
                                      command='command')],
            ),
            dict(
                name='test_action_added',
                node='node0',
                schedule=dict(interval='10s'),
                actions=[
                    dict(name='action_first', command='command_do_it')
                ]
            )
        ])

    post_config = dict(
        ssh_options=dict(
            agent=True,
            identities=['tests/test_id_rsa'],
        ),
        nodes=[
            dict(name='node0', hostname='batch0'),
            dict(name='node1', hostname='batch1'),
        ],
        node_pools=[dict(name='nodePool', nodes=['node0', 'node1'])],
        command_context={
            'a_variable': 'is_constant',
            'thischanges': 'tob'
        },
        jobs=[
            dict(
                name='test_unchanged',
                node='node0',
                schedule='daily',
                actions=[dict(name='action_unchanged',
                              command='command_unchanged') ]
            ),
            dict(
                name='test_change',
                node='nodePool',
                schedule='daily',
                actions=[
                    dict(name='action_change',
                         command='command_changed'),
                ],
            ),
            dict(
                name='test_daily_change',
                node='node0',
                schedule='daily',
                        actions=[dict(name='action_daily_change',
                                      command='command_changed')],
            ),
            dict(
                name='test_new',
                node='nodePool',
                schedule=dict(interval='20s'),
                actions=[dict(name='action_new',
                              command='command_new')]
            ),
            dict(
                name='test_action_added',
                node='node0',
                schedule=dict(interval='10s'),
                actions=[
                    dict(name='action_first', command='command_do_it'),
                    dict(name='action_second', command='command_ok'),
                ]
            )
        ])

    def _get_config(self, idx, output_dir):
        config = dict(self.post_config if idx else self.pre_config)
        config['output_stream_dir'] = output_dir
        return yaml.dump(config)

    @setup
    def setup_mcp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mcp = mcp.MasterControlProgram(self.test_dir, 'config')
        config = self._get_config(0, self.test_dir)
        self.mcp.apply_config(config_parse.load_config(config))

    @teardown
    def teardown_mcp(self):
        event.EventManager.get_instance().clear()
        filehandler.OutputPath(self.test_dir).delete()
        filehandler.FileHandleManager.reset()

    def reconfigure(self):
        config = self._get_config(1, self.test_dir)
        contents = config_parse.load_config(config)
        self.mcp.apply_config(contents, reconfigure=True)

    @suite('integration')
    def test_job_list(self):
        count = len(self.pre_config['jobs'])
        assert_equal(len(self.mcp.jobs), count)
        self.reconfigure()
        assert_equal(len(self.mcp.jobs), count)

    @suite('integration')
    def test_job_unchanged(self):
        assert 'test_unchanged' in self.mcp.jobs
        job_sched = self.mcp.jobs['test_unchanged']
        orig_job = job_sched.job
        run0 = job_sched.get_runs_to_schedule().next()
        run0.start()
        run1 = job_sched.get_runs_to_schedule().next()

        assert_equal(job_sched.job.name, "test_unchanged")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 1)
        assert_equal(action_map['action_unchanged'].name, 'action_unchanged')
        assert_equal(str(job_sched.job.scheduler), "DAILY")

        self.reconfigure()
        assert job_sched is self.mcp.jobs['test_unchanged']
        assert job_sched.job is orig_job

        assert_equal(len(job_sched.job.runs.runs), 2)
        assert_equal(job_sched.job.runs.runs[1], run0)
        assert_equal(job_sched.job.runs.runs[0], run1)
        assert run1.is_scheduled
        assert_equal(job_sched.job.context['a_variable'], 'is_constant')
        assert_equal(job_sched.job.context['thischanges'], 'tob')

    @suite('integration')
    def test_job_unchanged_disabled(self):
        job_sched = self.mcp.jobs['test_unchanged']
        orig_job = job_sched.job
        job_sched.get_runs_to_schedule().next()
        job_sched.disable()

        self.reconfigure()
        assert job_sched is self.mcp.jobs['test_unchanged']
        assert job_sched.job is orig_job
        assert not job_sched.job.enabled

    @suite('integration')
    def test_job_removed(self):
        assert 'test_remove' in self.mcp.jobs
        job_sched = self.mcp.jobs['test_remove']
        run0 = job_sched.get_runs_to_schedule().next()
        run0.start()
        run1 = job_sched.get_runs_to_schedule().next()

        assert_equal(job_sched.job.name, "test_remove")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 2)
        assert_equal(action_map['action_remove'].name, 'action_remove')

        self.reconfigure()
        assert not 'test_remove' in self.mcp.jobs
        assert not job_sched.job.enabled
        assert not run1.is_scheduled

    @suite('integration')
    def test_job_changed(self):
        assert 'test_change' in self.mcp.jobs
        job_sched = self.mcp.jobs['test_change']
        run0 = job_sched.get_runs_to_schedule().next()
        run0.start()
        job_sched.get_runs_to_schedule().next()
        assert_equal(len(job_sched.job.runs.runs), 2)

        assert_equal(job_sched.job.name, "test_change")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 2)

        self.reconfigure()
        new_job_sched = self.mcp.jobs['test_change']
        assert new_job_sched is job_sched
        assert new_job_sched.job is job_sched.job

        assert_equal(new_job_sched.job.name, "test_change")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 1)

        assert_equal(len(new_job_sched.job.runs.runs), 2)
        assert new_job_sched.job.runs.runs[1].is_starting
        assert new_job_sched.job.runs.runs[0].is_scheduled
        assert_equal(job_sched.job.context['a_variable'], 'is_constant')
        assert new_job_sched.job.context.base.job is new_job_sched.job

    @suite('integration')
    def test_job_changed_disabled(self):
        job_sched = self.mcp.jobs['test_change']
        job_sched.disable()
        assert not job_sched.job.enabled

        self.reconfigure()
        new_job_sched = self.mcp.jobs['test_change']
        assert not new_job_sched.job.enabled

    @suite('integration')
    def test_job_new(self):
        assert not 'test_new' in self.mcp.jobs
        self.reconfigure()

        assert 'test_new' in self.mcp.jobs
        job_sched = self.mcp.jobs['test_new']

        assert_equal(job_sched.job.name, "test_new")
        action_map = job_sched.job.action_graph.action_map
        assert_equal(len(action_map), 1)
        assert_equal(action_map['action_new'].name, 'action_new')
        assert_equal(action_map['action_new'].command, 'command_new')
        assert_equal(len(job_sched.job.runs.runs), 1)
        assert job_sched.job.runs.runs[0].is_scheduled

    @suite('integration')
    def test_daily_reschedule(self):
        job_sched = self.mcp.jobs['test_daily_change']

        job_sched.get_runs_to_schedule().next()

        assert_equal(len(job_sched.job.runs.runs), 1)
        run = job_sched.job.runs.runs[0]
        assert run.is_scheduled

        self.reconfigure()
        assert run.is_cancelled

        assert_equal(len(job_sched.job.runs.runs), 1)
        new_run = job_sched.job.runs.runs[0]
        assert new_run is not run
        assert new_run.is_scheduled
        assert_equal(run.run_time, new_run.run_time)

    @suite('integration')
    def test_action_added(self):
        self.reconfigure()
        job_sched = self.mcp.jobs['test_action_added']
        assert_length(job_sched.job.action_graph.action_map, 2)

if __name__ == '__main__':
    run()