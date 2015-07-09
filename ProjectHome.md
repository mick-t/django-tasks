Django-tasks is an asynchronous task management daemon, to execute long-running batch tasks (minutes, hours or even days) on a Django server.


Django-tasks is for a different usage from most other tasks frameworks ([Celery](http://ask.github.com/celery/), [Cue](http://charlesleifer.com/blog/idea-for-simple-task-queue/)...): this is **not** for numerous, quick, light, tasks, but for few, long, heavy, tasks. Typical usage is to batch process data for each model object, and give information about the processing to the user.

Also, no other software or library is needed. Django-tasks simply uses the Django database as a queue (and Tasks are a simple model); and each task is spawned as its own process.

### Main features ###

Features include:
  * Log gathering: at anytime, you can access the standard output created by your tasks,
  * Start time, end time... of course,
  * Task dependency: only run a task of some other dependent task(s) have run (useful when multiple tasks require that one long processing has already happened),
  * History (archive) of tasks already run on an object. This is helpful if there are errors or problem, to keep a log of what has run in the past,
  * Basic admin view that lets you see what has been, or is, running,
  * Cancel running tasks (kills the process).

This is now (August 2010) used in production for a hosted website, and a distributed product, so you should see fixes and improvements over time. Feedback is welcome.

It is tested on Linux and MacOS, and it should run on Windows (per [issue 16](https://code.google.com/p/django-tasks/issues/detail?id=16)); and on PostgreSQL and sqlite (with some caveats for sqlite, see below)

### Basic usage ###

To use django-tasks, you must:



  1. Checkout the code from SVN by running
```
svn checkout http://django-tasks.googlecode.com/svn/trunk/ djangotasks
```

> 2. Install django-tasks as an application on your Django server, by adding `djangotasks` to your `INSTALLED_APPS`, e.g., in your `settings.py`:
```
INSTALLED_APPS = (
    (...)
    'djangotasks',
    (...)
)
```


> 3. Set up the task daemon. It can run either as a thread in your process (provided you only run one server process) or as a separate process.

  * To run it in-process (as a thread), just set:

```
  DJANGOTASK_DAEMON_THREAD = True
```

in your settings.py. Warning ! this will start one scheduler thread for each of your server processes, which can be misleading. So only do that in development.

  * _(changed in [r28](https://code.google.com/p/django-tasks/source/detail?r=28): now a real daemon)_ To run it as a separate process, run:

```
   python manage.py taskd start
```

from a command line. This will start the task engine as a daemon. Then, to stop it, run:

```
   python manage.py taskd stop
```

and if you have any trouble, run:

```
   python manage.py taskd run
```

to see it run interactively.

PostgreSQL is recommended for that: with SQLite, there may be issues if you often update the tasks from the UI, since you may get into write locks.


> 4. In your code, register your task(s) by adding:
```
import djangotasks
djangotasks.register_task(YourModel.your_method_to_run, "Description of the method")
```
_(the API has changed in [r34](https://code.google.com/p/django-tasks/source/detail?r=34))_

> 5. In your code (probably in a view), execute the task by running:
```
import djangotasks
task = djangotasks.task_for_object(your_model_object.your_method_to_run)
djangotasks.run_task(task)
```
_(the API has changed in [r34](https://code.google.com/p/django-tasks/source/detail?r=34))_

You can then view the status of your task in the Admin module.

You can of course use the Task model in your own models and views, to provide specific user interface for your own tasks.



### Changelog ###

The API is getting stable (after [r34](https://code.google.com/p/django-tasks/source/detail?r=34)), but it may still change. You may need to upgrade your code or your data when getting a new version. Recent changes include:

  * [r31](https://code.google.com/p/django-tasks/source/detail?r=31): you must run the following script on your database:

```
from djangotasks.models import Task
for task in Task.objects.all():
    components = task.model.split('.')
    mod = __import__('.'.join(components[:-1]))
    for comp in components[1:]:
        mod = getattr(mod, comp)
    task.model = unicode(mod._meta)
    task.save()
```

  * [r34](https://code.google.com/p/django-tasks/source/detail?r=34): new API in [\_\_init\_\_.py](http://code.google.com/p/django-tasks/source/browse/trunk/__init__.py). You should modify your code to use the new API. Please contact me if what you were doing is not possible with the new API anymore. Also, support for tasks

  * [r35](https://code.google.com/p/django-tasks/source/detail?r=35): [South](http://south.aeracode.org/) upgrade scripts to upgrade from a version prior to [r34](https://code.google.com/p/django-tasks/source/detail?r=34). To use it, rename `djangotasks/south-migration` to `djangotasks-migration` and run the upgrade. From now on, we will provide South migration scripts to upgrade ealier databases.