"""
buildstockbatch.sampler.residential_quota
~~~~~~~~~~~~~~~
This object contains the code required for generating the set of simulations to execute

:author: Noel Merket, Ry Horsey
:copyright: (c) 2020 by The Alliance for Sustainable Energy
:license: BSD-3
"""
import docker
import logging
import os
import shutil
import subprocess
import sys
import time

from .base import BuildStockSampler
from .downselect import DownselectSamplerBase
from buildstockbatch.exc import ValidationError

logger = logging.getLogger(__name__)


class ResidentialQuotaSampler(BuildStockSampler):

    def __init__(self, parent, n_datapoints):
        """Residential Quota Sampler

        :param parent: BuildStockBatchBase object
        :type parent: BuildStockBatchBase (or subclass)
        :param n_datapoints: number of datapoints to sample
        :type n_datapoints: int
        """
        super().__init__(parent)
        self.validate_args(self.parent().project_filename, n_datapoints=n_datapoints)
        self.n_datapoints = n_datapoints

    @classmethod
    def validate_args(cls, project_filename, **kw):
        expected_args = set(['n_datapoints'])
        for k, v in kw.items():
            expected_args.discard(k)
            if k == 'n_datapoints':
                if not isinstance(v, int):
                    raise ValidationError('n_datapoints needs to be an integer')
                if v <= 0:
                    raise ValidationError('n_datapoints need to be >= 1')
            else:
                raise ValidationError(f'Unknown argument for sampler: {k}')
        if len(expected_args) > 0:
            raise ValidationError('The following sampler arguments are required: ' + ', '.join(expected_args))
        return True

    def _run_sampling_docker(self):
        docker_client = docker.DockerClient.from_env()
        tick = time.time()
        extra_kws = {}
        if sys.platform.startswith('linux'):
            extra_kws['user'] = f'{os.getuid()}:{os.getgid()}'
       
        for container in docker_client.containers.list():
            logger.debug("name: %s" % container.name)
            logger.debug("labels: %s" %container.labels)
        
        try:
            exist_test_containers = [i.name for i in docker_client.containers.list(all = True)]
            logger.debug(exist_test_containers)
            if 'buildstock_sampling_test' in exist_test_containers:
                logger.debug('buildstock_sampling_test exists')
                exist_test_container =  docker_client.containers.get('buildstock_sampling_test')
                exist_test_container.stop()
                exist_test_container.remove(force=True)
        except Exception as e :
            logger.debug("docker_test_closing error: %s" % e)
        # logger.debug(self.buildstock_dir)
        if os.environ['HOST_PATH']:
            host_path  = "/"+os.environ['HOST_PATH'].replace("\\","/").replace(":","")
            docker_path =   os.path.realpath(self.buildstock_dir.replace(os.environ['PWD'],host_path))
        else:
            docker_path = self.buildstock_dir
        buildstock_dir_path = os.path.realpath(self.buildstock_dir)
        project_dir_path = os.path.realpath(os.path.abspath(os.path.join(buildstock_dir_path,self.cfg['project_directory'])))
        logger.debug(docker_path)
        logger.debug(project_dir_path)
       
        if os.path.commonprefix([buildstock_dir_path, project_dir_path]) != buildstock_dir_path: ## refactor project_dir path
            docker_project_path = os.path.realpath(os.path.abspath(os.path.join(docker_path,self.cfg['project_directory'])))
            docker_output_path =  os.path.join(os.path.basename(docker_project_path),'buildstock.csv')
            volumes_hash = {
                docker_path: {'bind': '/var/simdata/openstudio', 'mode': 'rw'},
                docker_project_path: {'bind': "/var/simdata/openstudio/%s" % os.path.basename(docker_project_path), 'mode': 'rw'},
            }
        else:
            docker_project_path = self.cfg['project_directory']
            docker_output_path =  'buildstock.csv'
            volumes_hash = {
                docker_path: {'bind': '/var/simdata/openstudio', 'mode': 'rw'},
             
            }
        logger.debug(volumes_hash)
        container_output = docker_client.containers.run(
            self.parent().docker_image,
            command = "ls -la %s " % '/var/simdata/openstudio',
            remove=True,
            volumes=volumes_hash ,
            name='buildstock_sampling_test',
            **extra_kws
        )
        for line in container_output.decode('utf-8').split('\n'):
            logger.debug(line)
        # logger.debug(  " ".join([
        #         'ruby',
        #         'resources/run_sampling.rb',
        #         # '-p', self.cfg['project_directory'],
        #         '-p', docker_project_path,
        #         '-n', str(self.n_datapoints),
        #         # '-o', 'buildstock.csv'
        #         '-o', docker_output_path
        #     ]))
       
        container_output = docker_client.containers.run(
            self.parent().docker_image,
            [
                'ruby',
                'resources/run_sampling.rb',
                # '-p', self.cfg['project_directory'],
                '-p', os.path.basename(docker_project_path),
                '-n', str(self.n_datapoints),
                # '-o', 'buildstock.csv'
                '-o', docker_output_path
            ],
            # remove=True,
            auto_remove=True,
            # volumes={
            #     docker_path: {'bind': '/var/simdata/openstudio', 'mode': 'rw'}
            # },
            volumes=volumes_hash ,
            name='buildstock_sampling',
            **extra_kws
        )
        tick = time.time() - tick
        for line in container_output.decode('utf-8').split('\n'):
            logger.debug(line)
        logger.debug('Sampling took {:.1f} seconds'.format(tick))
        logger.debug('self.csv_path: {}'.format(self.csv_path))
      
        destination_filename = self.csv_path
        if os.path.exists(destination_filename):
            os.remove(destination_filename)
        shutil.move(
            os.path.join(self.buildstock_dir, 'resources', 'buildstock.csv'),
            destination_filename
        )
        return destination_filename

    def _run_sampling_singularity(self):
        args = [
            'singularity',
            'exec',
            '--contain',
            '--home', '{}:/buildstock'.format(self.buildstock_dir),
            '--bind', '{}:/outbind'.format(os.path.dirname(self.csv_path)),
            self.parent().singularity_image,
            'ruby',
            'resources/run_sampling.rb',
            '-p', self.cfg['project_directory'],
            '-n', str(self.n_datapoints),
            '-o', '../../outbind/{}'.format(os.path.basename(self.csv_path))
        ]
        logger.debug(f"Starting singularity sampling with command: {' '.join(args)}")
        subprocess.run(args, check=True, env=os.environ, cwd=self.parent().output_dir)
        logger.debug("Singularity sampling completed.")
        return self.csv_path


class ResidentialQuotaDownselectSampler(DownselectSamplerBase):
    SUB_SAMPLER_CLASS = ResidentialQuotaSampler
