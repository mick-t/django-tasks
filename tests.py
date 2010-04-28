#
# Copyright (c) 2010 by nexB, Inc. http://www.nexb.com/ - All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
# 
#     1. Redistributions of source code must retain the above copyright notice,
#        this list of conditions and the following disclaimer.
#    
#     2. Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.
# 
#     3. Neither the names of Django, nexB, Django-tasks nor the names of the contributors may be used
#        to endorse or promote products derived from this software without
#        specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import with_statement 

import sys
import StringIO
import os
import unittest
import tempfile
import time
import inspect
from os.path import join, dirname

from models import Task, TaskManager

class StandardOutputCheck(object):
    def __init__(self, test, expected_stdout = None, fail_if_different=True):
        self.test = test
        self.expected_stdout = expected_stdout or ''
        self.fail_if_different = fail_if_different
        
    def __enter__(self):
        self.stdout = sys.stdout
        sys.stdout = StringIO.StringIO()
        
    def __exit__(self, type, value, traceback):
        # Restore state
        self.stdoutvalue = sys.stdout.getvalue()
        sys.stdout = self.stdout

        # Check the output only if no exception occured (to avoid "eating" test failures)
        if type:
            return
        
        if self.fail_if_different:
            self.test.assertEquals(self.expected_stdout, self.stdoutvalue)

class TestModel(object):
    ''' A mock Model object for task tests'''
    class Manager(object):
        def get(self, pk):
            if pk not in ['key1', 'key2', 'key3']:
                raise Exception("Not a good object loaded")
            return TestModel()
    pk = '10'
    objects = Manager()
    def run_something(self, msg=''):
        import time
        time.sleep(2)
        print "running something..."
        import sys
        sys.stdout.flush()
        time.sleep(2)
        print "still running..."
        open('/tmp/x', 'w').writelines(["finished"])
        return "finished"
    
    def run_something_else(self):
        pass

    def run_something_failing(self):
        import time
        time.sleep(1)
        print "running, will fail..."
        import sys
        sys.stdout.flush()
        time.sleep(1)
        raise Exception("Failed !")

    def run_something_with_required(self):
        import time
        time.sleep(2)
        print "running required..."
        import sys
        sys.stdout.flush()
        time.sleep(2)
        return "finished required"

    def run_something_with_two_required(self):
        # not called in the tests
        pass

    def run_a_method_that_is_not_registered(self):
        # not called in the tests
        pass

    def run_something_fast(self):
        print "Doing something fast"
        time.sleep(1)

class ViewsTestCase(unittest.TestCase):
    def failUnlessRaises(self, excClassOrInstance, callableObj, *args, **kwargs):
        # improved method compared to unittest.TestCase.failUnlessRaises:
        # also check the content of the exception
        if inspect.isclass(excClassOrInstance):
            return unittest.TestCase.failUnlessRaises(self, excClassOrInstance, callableObj, *args, **kwargs)

        excClass = excClassOrInstance.__class__
        try:
            callableObj(*args, **kwargs)
        except excClass, e:
            self.assertEquals(str(excClassOrInstance), str(e))
        else:
            if hasattr(excClass,'__name__'): excName = excClass.__name__
            else: excName = str(excClass)
            raise self.failureException, "%s not raised" % excName

    assertRaises = failUnlessRaises

    def setUp(self):
        TaskManager.DEFINED_TASKS['djangotasks.tests.TestModel'] = \
            [('run_something', "Run a successful task", ''),
             ('run_something_else', "Run an empty task", ''),
             ('run_something_failing', "Run a failing task", ''),
             ('run_something_with_required', "Run a task with a required task", 'run_something'),
             ('run_something_with_two_required', "Run a task with two required task", 'run_something,run_something_with_required'),
             ('run_something_fast', "Run a fast task", ''),
             ]

        
    def tearDown(self):
        del TaskManager.DEFINED_TASKS['djangotasks.tests.TestModel']
        for task in Task.objects.filter(model='djangotasks.tests.TestModel'):
            task.delete()

    def test_tasks_import(self):
        from djangotasks.models import _my_import
        self.assertEquals(TestModel, _my_import('djangotasks.tests.TestModel'))

    def _create_task(self, method, object_id):
        from djangotasks.models import _qualified_class_name
        return Task.objects._create_task(_qualified_class_name(method.im_class), 
                                         method.im_func.__name__, 
                                         object_id)


    def test_tasks_invalid_method(self):
        self.assertRaises(Exception("No task defined for this method"), 
                          self._create_task, TestModel.run_a_method_that_is_not_registered, 'key1')

        class NotAValidModel(object):
            def a_method(self):
                pass
        self.assertRaises(Exception("No task defined for this model"), 
                          self._create_task, NotAValidModel.a_method, 'key1')
            
        self.assertRaises(Exception("Not a good object loaded"), 
                          self._create_task, TestModel.run_something, 'key_that_does_not_exist')

    def test_tasks_register(self):
        class MyClass(object):
            def mymethod1(self):
                pass

            def mymethod2(self):
                pass
            
            def mymethod3(self):
                pass
                
                
        from djangotasks.models import register_task
        try:
            register_task(MyClass.mymethod3, None, MyClass.mymethod1, MyClass.mymethod2)
            register_task(MyClass.mymethod1, '''Some documentation''', MyClass.mymethod2)
            register_task(MyClass.mymethod2, '''Some other documentation''')
            self.assertEquals([('mymethod3', '', 'mymethod1,mymethod2'),
                               ('mymethod1', 'Some documentation', 'mymethod2'),
                               ('mymethod2', 'Some other documentation', '')],
                              TaskManager.DEFINED_TASKS['djangotasks.tests.MyClass'])
        finally:
            del TaskManager.DEFINED_TASKS['djangotasks.tests.MyClass']

    def test_tasks_run_successful(self):
        task = self._create_task(TestModel.run_something, 'key1')
        Task.objects.run_task(task.pk)
        with StandardOutputCheck(self, "Starting task " + str(task.pk) + "... started.\n"):
            Task.objects._do_schedule()
        time.sleep(8)
        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals(u'running something...\nstill running...\n'
                          #+ u'finished\n' # weird... sometimes this is returned, sometimes not
                          , new_task.log)
        self.assertEquals("successful", new_task.status)
        self.assertEquals("finished", open('/tmp/x').readlines()[0])

    def test_tasks_run_cancel_running(self):
        task = self._create_task(TestModel.run_something, 'key1')
        Task.objects.run_task(task.pk)
        with StandardOutputCheck(self, "Starting task " + str(task.pk) + "... started.\n"):
            Task.objects._do_schedule()
        time.sleep(5)
        Task.objects.cancel_task(task.pk)
        output_check = StandardOutputCheck(self, fail_if_different=False)
        with output_check:
            Task.objects._do_schedule()
            time.sleep(1)
        self.assertTrue(("Cancelling task " + str(task.pk) + "...") in output_check.stdoutvalue)
        self.assertTrue("cancelled.\n" in output_check.stdoutvalue)
        self.assertTrue('INFO: failed to mark tasked as finished, from status "running" to "unsuccessful" for task 3. May have been finished in a different thread already.\n'
                        in output_check.stdoutvalue)

        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("cancelled", new_task.status)            
        self.assertTrue(u'running something...' in new_task.log)
        self.assertFalse(u'still running...' in new_task.log)
        self.assertFalse('finished' in new_task.log)

    def test_tasks_run_cancel_scheduled(self):
        task = self._create_task(TestModel.run_something, 'key1')
        with StandardOutputCheck(self):
            Task.objects._do_schedule()
        Task.objects.run_task(task.pk)
        Task.objects.cancel_task(task.pk)
        with StandardOutputCheck(self, "Cancelling task " + str(task.pk) + "... cancelled.\n"):
            Task.objects._do_schedule()
        time.sleep(1)
        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("cancelled", new_task.status)            
        self.assertEquals("", new_task.log)

    def test_tasks_run_failing(self):
        task = self._create_task(TestModel.run_something_failing, 'key1')
        Task.objects.run_task(task.pk)
        with StandardOutputCheck(self, "Starting task " + str(task.pk) + "... started.\n"):
            Task.objects._do_schedule()
        time.sleep(8)
        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("unsuccessful", new_task.status)
        self.assertTrue(u'running, will fail...' in new_task.log)
        self.assertTrue(u'raise Exception("Failed !")' in new_task.log)
        self.assertTrue(u'Exception: Failed !' in new_task.log)
        time.sleep(1)
    
    def test_tasks_get_tasks_for_object(self):
        tasks = Task.objects.tasks_for_object(TestModel, 'key2')
        self.assertEquals(6, len(tasks))
        self.assertEquals('defined', tasks[0].status)
        self.assertEquals('defined', tasks[1].status)
        self.assertEquals('run_something', tasks[0].method)
        self.assertEquals('run_something_else', tasks[1].method)

    def test_tasks_get_task_for_object(self):
        self.assertRaises(Exception("Method 'run_doesn_not_exists' not registered for model 'djangotasks.tests.TestModel'"), 
                          Task.objects.task_for_object, TestModel, 'key2', 'run_doesn_not_exists')
        task = Task.objects.task_for_object(TestModel, 'key2', 'run_something')
        self.assertEquals('defined', task.status)
        self.assertEquals('run_something', task.method)

    def test_tasks_revision(self):
        task = Task.objects.task_for_object(TestModel, 'key2', 'run_something')
        Task.objects.run_task(task.pk)
        Task.objects.mark_start(task.pk, '12345')
        task = Task.objects.task_for_object(TestModel, 'key2', 'run_something')
        from os.path import exists, dirname, join
        import settings
        if exists(join(dirname(settings.__file__), '.svn')):
            self.assertTrue(task.revision > 0)
        else:
            self.assertEquals(0, task.revision)

    def test_tasks_archive_task(self):
        tasks = Task.objects.tasks_for_object(TestModel, 'key3')
        task = tasks[0]
        self.assertTrue(task.pk)
        task.status = 'successful'
        task.save()
        self.assertEquals(False, task.archived)
        new_task = self._create_task(TestModel.run_something,
                                     'key3')
        self.assertTrue(new_task.pk)
        self.assertTrue(task.pk != new_task.pk)
        old_task = Task.objects.get(pk=task.pk)        
        self.assertEquals(True, old_task.archived, "Task should have been archived once a new one has been created")

    def test_tasks_get_required_tasks(self):
        task = self._create_task(TestModel.run_something_with_required, 'key1')
        self.assertEquals(['run_something'],
                          [required_task.method for required_task in task.get_required_tasks()])
        
        
        task = self._create_task(TestModel.run_something_with_two_required, 'key1')
        self.assertEquals(['run_something', 'run_something_with_required'],
                          [required_task.method for required_task in task.get_required_tasks()])

    def test_tasks_required_task(self):
        task = self._create_task(TestModel.run_something_with_required, 'key1')
        Task.objects.run_task(task.pk)
        with StandardOutputCheck(self):
            Task.objects._do_schedule()
        time.sleep(3)
        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("scheduled", new_task.status)
        
        required_task = self._create_task(TestModel.run_something, 'key1')
        Task.objects.run_task(required_task.pk)
        with StandardOutputCheck(self, "Starting task " + str(required_task.pk) + "... started.\n"):
            Task.objects._do_schedule()
        time.sleep(8)
        new_task = Task.objects.get(pk=required_task.pk)
        self.assertEquals("successful", new_task.status)
        
        with StandardOutputCheck(self, "Starting task " + str(task.pk) + "... started.\n"):
            Task.objects._do_schedule()
        time.sleep(8)
        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("successful", new_task.status)

    def test_tasks_run_again(self):
        tasks = Task.objects.tasks_for_object(TestModel, 'key3')
        task = tasks[5]
        self.assertEquals('run_something_fast', task.method)
        Task.objects.run_task(task.pk)
        with StandardOutputCheck(self, "Starting task " + str(task.pk) + "... started.\n"):
            Task.objects._do_schedule()
        time.sleep(4)
        new_task = Task.objects.get(pk=task.pk)
        self.assertEquals("successful", new_task.status)
        Task.objects.run_task(task.pk)
        output_check = StandardOutputCheck(self, fail_if_different=False)
        with output_check:
            Task.objects._do_schedule()
        import re
        pks = re.findall(r'(\d+)', output_check.stdoutvalue)
        self.assertEquals(1, len(pks))
        self.assertEquals("Starting task " + pks[0] + "... started.\n", output_check.stdoutvalue)
        time.sleep(4)
        new_task = Task.objects.get(pk=int(pks[0]))
        self.assertTrue(new_task.pk != task.pk)
        self.assertEquals("successful", new_task.status)
        tasks = Task.objects.tasks_for_object(TestModel, 'key3')
        self.assertEquals(new_task.pk, tasks[5].pk)
        

    def test_tasks_exception_in_thread(self):
        task = self._create_task(TestModel.run_something, 'key1')
        Task.objects.run_task(task.pk)
        task = self._create_task(TestModel.run_something, 'key1')
        task_delete = self._create_task(TestModel.run_something, 'key1')
        task_delete.delete()
        try:
            Task.objects.get(pk=task.pk)
            self.fail("Should throw an exception")
        except Exception, e:
            self.assertEquals("Task matching query does not exist.", str(e))
            
        output_check = StandardOutputCheck(self, fail_if_different=False)
        with output_check:
            task.do_run()
            time.sleep(2)
        self.assertTrue("Exception: Failed to mark task with " in output_check.stdoutvalue)
        self.assertTrue("as started, task does not exist" in output_check.stdoutvalue)
        self.assertTrue('INFO: failed to mark tasked as finished, from status "running" to "unsuccessful" for task' in output_check.stdoutvalue)
