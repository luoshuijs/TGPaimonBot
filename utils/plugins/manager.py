import os
from glob import glob
from importlib import import_module
from os import path
from typing import List, Union

from telegram.ext import Application

from logger import Log

PluginsClass: List[object] = []


def listener_plugins_class():
    """监听插件
    :return: None
    """

    def decorator(func: object):
        PluginsClass.append(func)
        return func

    return decorator


class PluginsManager:
    def __init__(self):
        self.plugin_list: List[str] = []  # 用于存储文件名称
        self.exclude_list: List[str] = []

    def refresh_list(self, plugin_paths):
        self.plugin_list.clear()
        plugin_paths = glob(plugin_paths)
        for plugin_path in plugin_paths:
            if plugin_path.startswith('__'):
                continue
            if os.path.isdir(plugin_path):
                plugin_path = os.path.basename(plugin_path)
                self.plugin_list.append(plugin_path)
                continue
            module_name = path.basename(path.normpath(plugin_path))
            root, ext = os.path.splitext(module_name)
            if ext == ".py":
                self.plugin_list.append(root)

    def add_exclude(self, exclude: Union[str, List[str]]):
        if isinstance(exclude, str):
            self.exclude_list.append(exclude)
        elif isinstance(exclude, list):
            self.exclude_list.extend(exclude)
        else:
            raise TypeError

    def import_module(self):
        for plugin_name in self.plugin_list:
            if plugin_name not in self.exclude_list:
                try:
                    import_module(f"plugins.{plugin_name}")
                except ImportError as exc:
                    Log.warning(f"插件 {plugin_name} 导入失败", exc)
                except ImportWarning as exc:
                    Log.warning(f"插件 {plugin_name} 加载成功但有警告", exc)
                except BaseException as exc:
                    Log.warning(f"插件 {plugin_name} 加载失败", exc)
                else:
                    Log.debug(f"插件 {plugin_name} 加载成功")

    @staticmethod
    def add_handler(application: Application):
        for func in PluginsClass:
            if callable(func):
                try:
                    handlers_list = func.create_handlers()
                    for handler in handlers_list:
                        application.add_handler(handler)
                except AttributeError as exc:
                    if "create_handlers" in str(exc):
                        Log.error("创建 handlers 函数未找到", exc)
                    Log.error("初始化Class失败", exc)
                except BaseException as exc:
                    Log.error("初始化Class失败", exc)
                finally:
                    pass
