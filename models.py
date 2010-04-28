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

import os
import time
import sys
from django.db import models
from datetime import datetime
from os.path import join, exists, dirname, abspath
from collections import defaultdict
from django.db import transaction, connection

def _qualified_class_name(the_class):
    import inspect
    if not inspect.isclass(the_class):
        raise Exception(repr(the_class) + "is not a class")
    return the_class.__module__ + '.' + the_class.__name__


# this could be a decorator... if we could access the class at function definition time
def register_task(method, documentation, *required_methods):
    import inspect
    if not inspect.ismethod(method):
        raise Exception(repr(method) + "is not a class method")
    model = _qualified_class_name(method.im_class)
    for required_method in required_methods:
        if not inspect.ismethod(required_method):
            raise Exception(repr(required_method) + "is not a class method")
            
    TaskManager.DEFINED_TASKS[model].append((method.im_func.__name__, 
                                             documentation if documentation else '',
                                             ','.join(required_method.im_func.__name__ 
                                                      for required_method in required_methods)))
                   
class TaskManager(models.Manager):
    DEFINED_TASKS = defaultdict(list)

    def task_for_object(self, the_class, object_id, method):
        model = _qualified_class_name(the_class)
        if method not in [m for m, _, _ in TaskManager.DEFINED_TASKS[model]]:
            raise Exception("Method '%s' not registered for model '%s'" % (method, model))

        return self.get_or_create(model=model, 
                                  method=method,
                                  object_id=str(object_id),
                                  archived=False)[0]

    def tasks_for_object(self, the_class, object_id):
        model = _qualified_class_name(the_class)

        return [self.get_or_create(model=model, 
                                   method=method,
                                   object_id=str(object_id), 
                                   description=description,
                                   required_methods=required_methods,
                                   archived=False)[0]
                for method, description, required_methods in TaskManager.DEFINED_TASKS[model]]
            
    def run_task(self, pk):
        task = self.get(pk=pk)
        if task.status in ["scheduled", "running", 
                           "requested_cancel", ]:
            raise Exception("Task already running, cannot run again")
        if task.status in ["cancelled", "successful", "unsuccessful"]:
            task = self._create_task(task.model, 
                                     task.method, 
                                     task.object_id)

        task.status = "scheduled"
        task.save()

    def cancel_task(self, pk):
        task = self.get(pk=pk)
        if task.status not in ["scheduled", "running"]:
            raise Exception("Cannot cancel task that has not been scheduled or is not running")

        # If the task is still scheduled, mark it requested for cancellation also:
        # if it is currently starting, that's OK, it'll stay marked as "requested_cancel" in mark_start
        self._set_status(pk, "requested_cancel", "scheduled")
        self._set_status(pk, "requested_cancel", "running")


    # The methods below are for internal use on the server. Don't use them directly.
    def _create_task(self, model, method, object_id):
        if model not in TaskManager.DEFINED_TASKS:
            raise Exception("No task defined for this model")
        if method not in [taskdef[0] for taskdef in TaskManager.DEFINED_TASKS[model]]:
            raise Exception("No task defined for this method")

        taskdef = [taskdef for taskdef in TaskManager.DEFINED_TASKS[model] 
                   if taskdef[0] == method][0]
        task, _ = self.get_or_create(model=model, 
                                     method=method,
                                     object_id=str(object_id), 
                                     status__in=["defined", "scheduled", 
                                                 "running", "requested_cancel"],
                                     description = taskdef[1],
                                     required_methods = taskdef[2],
                                     archived=False)
        return task

    def append_log(self, pk, log):
        if log:
            connection.cursor().execute('UPDATE ' + Task._meta.db_table + ' SET log = log || %s WHERE id = %s', [log, pk])
            transaction.commit_unless_managed()

    def mark_start(self, pk, pid):
        # Set the start information in all cases...
        from django.utils import version
        import settings
        try:
            revision = int(version.get_svn_revision(dirname(settings.__file__))[4:])
        except:
            revision = 0
        try:
            connection.cursor().execute('UPDATE ' + Task._meta.db_table + ' SET start_date = %s, pid = %s, revision = %s WHERE id = %s', 
                                        [datetime.now(),
                                         pid, 
                                         revision,
                                         pk])
        finally:
            transaction.commit_unless_managed()

        # ... but mark as running only if it is currently "scheduled".
        # That way, if it has been set to "requested_cancel" already, it will be cancelled at the next loop of the scheduler
        self._set_status(pk, "running", "scheduled")

    def _set_status(self, pk, new_status, existing_status):
        connection.cursor().execute('UPDATE ' + Task._meta.db_table + ' SET status = %s WHERE id = %s AND status = %s', [new_status, pk, existing_status])
        transaction.commit_unless_managed()


    def mark_finished(self, pk, new_status, existing_status):
        connection.cursor().execute('UPDATE ' + Task._meta.db_table + ' SET status = %s, end_date = %s, pid = 0 WHERE id = %s AND status = %s', 
                                    [new_status, 
                                     datetime.now(),
                                     pk, existing_status])
        transaction.commit_unless_managed()

    # This is for use on the server. Don't use it directly.
    def exec_task(self, pk):
        task = self.get(pk=pk)
        try:
            the_method = task.find_method()
            the_method()
        finally:
            import sys
            sys.stdout.flush()
            sys.stderr.flush()
    
    # This is for use in the scheduler only. Don't use it directly
    def scheduler(self):
        print "Starting scheduler..."
        while True:
            try:
                self._do_schedule()
            except Exception, e:
                print "Scheduler exception: " + str(e)
            # Loop time must be enough to let the threads that may have be started call mark_start
            time.sleep(5)

    def _do_schedule(self):
        # First cancel any task that needs to be cancelled...
        tasks = self.filter(status="requested_cancel",
                            archived=False)
        for task in tasks:
            print "Cancelling task %d..." % task.pk, 
            task.do_cancel()
            print "cancelled."

        # ... Then start any new task
        tasks = self.filter(status="scheduled",
                            archived=False)
        for task in tasks:
            # only run if all the required tasks have been successful
            if all(required_task.status == "successful"
                   for required_task in task.get_required_tasks()):
                print "Starting task %s..." % task.pk, 
                task.do_run()
                print "started."
                # only start one task at a time
                break
                
def _my_import(name):
    components = name.split('.')
    mod = __import__('.'.join(components[:-1]))
    for comp in components[1:]:
        mod = getattr(mod, comp)
    return mod


STATUS_TABLE = [('defined', 'Ready for scan'),
                ('scheduled', 'Scan scheduled'),
                ('running', 'Scan in progress',),
                ('requested_cancel', 'Scan cancelled'),
                ('cancelled', 'Scan cancelled'),
                ('successful', 'Successfully scanned'),
                ('unsuccessful', 'Scan error'),
                ]

          
class Task(models.Model):

    model = models.CharField(max_length=200)
    method = models.CharField(max_length=200)
    
    object_id = models.CharField(max_length=200)
    pid = models.IntegerField(null=True)

    start_date = models.DateTimeField(null=True)
    end_date = models.DateTimeField(null=True)

    revision = models.IntegerField(null=True, default=0) # Subversion revision of the code used to run a task
    status = models.CharField(max_length=200,
                              default="defined",
                              choices=STATUS_TABLE,
                              )
    description = models.CharField(max_length=100, default='', null=True, blank=True)
    log = models.TextField(default='', null=True, blank=True)

    archived = models.BooleanField(default=False) # for history
    required_methods = models.CharField(max_length=200, default='', null=True, blank=True)  # comma-separated list of the required methods

    def __unicode__(self):
        return u'%s - %s.%s.%s' % (self.id, self.model.split('.')[-1], self.object_id, self.method)

    def status_string(self):
        '''
        Display the status (probably a computed field based on tasks: 
        "Scan scheduled", "Scan in progress"
        '''
        return dict(STATUS_TABLE)[self.status]

    # Only for use by the manager: do not call directly
    def do_run(self):
        if self.status != "scheduled":
            raise Exception("Task not scheduled, cannot run again")

        def exec_thread():
            import sys
            import time
            import subprocess

            returncode = -1
            try:
                import manage
                proc = subprocess.Popen([sys.executable, 
                                         manage.__file__, 
                                         'runtask', 
                                         str(self.pk)],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        close_fds=True)
                Task.objects.mark_start(self.pk, proc.pid)
                buf = ''
                t = time.time()
                while proc.poll() is None:
                    line = proc.stdout.readline()
                    buf += line
                    if (time.time() - t > 1): # Save the log once every second max
                        Task.objects.append_log(self.pk, buf)
                        buf = ''
                        t = time.time()
                Task.objects.append_log(self.pk, buf)
                
                # Need to continue reading for a while: sometimes we miss some output
                buf = ''
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    buf += line
                Task.objects.append_log(self.pk, buf)

                returncode = proc.returncode
            except Exception, e:
                try:
                    Task.objects.append_log(self.pk, "Exception in calling thread: " + str(e))
                except Exception, ee:
                    print "Exception in calling thread: " + str(e)
                    # if we can't log it, raise it
                    #raise e

            Task.objects.mark_finished(self.pk,
                                       "successful" if returncode == 0 else "unsuccessful",
                                       "running")
            
        import thread
        thread.start_new_thread(exec_thread, ())

    def do_cancel(self):
        if self.status != "requested_cancel":
            raise Exception("Cannot cancel task if not requested")

        try:
            if not self.pid:
                # This can happen if the task was only scheduled when it was cancelled.
                # There could be risk that the task starts *while* we are cancelling it, 
                # and we will mark it as cancelled, but in fact the process will not have been killed/
                # However, it won't happen because (in the scheduler loop) we *wait* after starting tasks, 
                # and before cancelling them. So no need it'll happen synchronously.
                return
                
            import signal
            os.kill(self.pid, signal.SIGTERM)
        except OSError, e:
            # could happen if the process *just finished*. Fail cleanly
            raise Exception('Failed to cancel task model=%s, method=%s, object=%s: %s' % (self.model, self.method, self.object_id, str(e)))
        finally:
            Task.objects.mark_finished(self.pk, "cancelled", "requested_cancel")

    def save(self, *args, **kwargs):
        if not self.pk:
            # new object: check if the method indeed exists
            self.find_method() # will throw an exception if not defined
            
            # and time to archive the old ones
            for task in Task.objects.filter(model=self.model, 
                                            method=self.method,
                                            object_id=self.object_id,
                                            archived=False):
                task.archived = True
                task.save()

        super(Task, self).save(*args, **kwargs)

    def get_required_tasks(self):
        def _taskdef(method):
            return [taskdef for taskdef in TaskManager.DEFINED_TASKS[self.model] 
                    if taskdef[0] == method][0]

        return [Task.objects.get_or_create(model=self.model, 
                                           method=method,
                                           object_id=self.object_id, 
                                           description = _taskdef(method)[1],
                                           required_methods = _taskdef(method)[2],
                                           archived=False)[0]
                for method in self.required_methods.split(',') if method]
    
    def find_method(self):
        the_class = _my_import(self.model)
        object = the_class.objects.get(pk=self.object_id)
        return getattr(object, self.method)

    def can_run(self):
        return self.status not in ["scheduled", "running", "requested_cancel", ] #"successful"
            
    objects = TaskManager()

from django.conf import settings
if 'DJANGOTASK_DAEMON_THREAD' in dir(settings) and settings.DJANGOTASK_DAEMON_THREAD:
    import thread
    thread.start_new_thread(Task.objects.scheduler, ())
