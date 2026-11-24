# -*- coding: utf-8 -*-
# Youcef ADDA | GEODECI | https://geodeci.xyz/ | youcef.geodesien@gmail.com
"""Réception QGIS4 isolée, avec réseau et profils métier neutralisés.

Lancer avec bin/python-qgis.bat de QGIS4. --script exécute un scénario dédié.
La sortie native de Qt n'est pas éprouvée par ce runner : les preuves sont
enregistrées avant l'arrêt du processus pour isoler la réception fonctionnelle.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import tempfile
import traceback
import unittest
import faulthandler

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('tests',nargs='*')
parser.add_argument('--script')
parser.add_argument('--result')
args=parser.parse_args()
runtime=Path(tempfile.mkdtemp(prefix='transformer-reception-'))
faulthandler.enable()
faulthandler.dump_traceback_later(60,repeat=False)
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QT_QPA_FONTDIR']='C:/Windows/Fonts'
os.environ['QGIS_CUSTOM_CONFIG_PATH']=str(runtime/'qgis')
os.environ['QGIS_AUTH_DB_DIR_PATH']=str(runtime/'auth')
(runtime/'auth').mkdir()
os.environ['TEMP']=os.environ['TMP']=str(runtime)
tempfile.tempdir=str(runtime)
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT.parent))
sys.path.insert(0,str(ROOT))
def deny_network(*_args,**_kwargs):
    raise RuntimeError('Réseau interdit dans la réception isolée')
socket.create_connection=deny_network
import psycopg2
psycopg2.connect=deny_network
from qgis.core import QgsApplication, Qgis
from qgis.PyQt.QtCore import QSettings, QT_VERSION_STR, PYQT_VERSION_STR
from qgis.PyQt.QtGui import QFontDatabase, QFont
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
for fmt in (QSettings.Format.NativeFormat,QSettings.Format.IniFormat):
    for scope in (QSettings.Scope.UserScope,QSettings.Scope.SystemScope):
        QSettings.setPath(fmt,scope,str(runtime/'settings'))
app=QgsApplication([],True,str(runtime/'profile'))
app.setOrganizationName('TransformerReception')
app.setApplicationName('ReceptionIsolee')
app.initQgis()
print('QGIS_INITIALIZED '+str(runtime),flush=True)
for file in ('segoeui.ttf','segoeuib.ttf','seguisb.ttf','arial.ttf','consola.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+file)
app.setFont(QFont('Segoe UI',10))
# Neither loading a window nor a timer may read a real connection profile.
from Transfomer.pg.postgresql_integration import PostgreSQLConfigWidget
PostgreSQLConfigWidget._connections_path=lambda self:str(runtime/'connections.json')
PostgreSQLConfigWidget._legacy_path=lambda self:str(runtime/'absent-legacy.json')
PostgreSQLConfigWidget.auto_test_connection=lambda self:None
result={'environment':{'qgis':Qgis.QGIS_VERSION,'qt':QT_VERSION_STR,'pyqt':PYQT_VERSION_STR,'mode':'offscreen','network':'blocked','runtime':str(runtime),'teardown':'not_covered'}}
code=0
try:
    if args.script:
        runpy.run_path(args.script,init_globals={'reception_app':app,'reception_runtime':runtime},run_name='__main__')
        result['script']='completed'
    else:
        suite=unittest.TestSuite()
        paths=args.tests or ['tests/test_pg_integrity.py','tests/test_recipe_integrity.py','tests/test_widgets_recipe.py','tests/test_workflow_qgis4.py','tests/test_export_tasks.py','tests/test_pg_dialog_qgis4.py']
        for index,file in enumerate(paths):
            file_name,_,test_name=file.partition('::')
            path=ROOT/file_name
            if not path.exists():
                raise FileNotFoundError(path)
            spec=importlib.util.spec_from_file_location(f'transformer_reception_{index}',path)
            module=importlib.util.module_from_spec(spec)
            sys.modules[spec.name]=module
            spec.loader.exec_module(module)
            suite.addTests(unittest.defaultTestLoader.loadTestsFromName(test_name,module) if test_name else unittest.defaultTestLoader.loadTestsFromModule(module))
        outcome=unittest.TextTestRunner(verbosity=2).run(suite)
        result.update(tests_run=outcome.testsRun,failures=[{'test':str(t),'trace':v} for t,v in outcome.failures],errors=[{'test':str(t),'trace':v} for t,v in outcome.errors],skipped=[{'test':str(t),'reason':v} for t,v in outcome.skipped],successful=outcome.wasSuccessful())
        code=0 if outcome.wasSuccessful() else 1
except BaseException:
    result['fatal']=traceback.format_exc()
    print(result['fatal'],flush=True)
    code=1
destination=Path(args.result) if args.result else runtime/'resultats.json'
destination.parent.mkdir(parents=True,exist_ok=True)
destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('RECEPTION_RESULT '+str(destination),flush=True)
sys.stdout.flush()
sys.stderr.flush()
if os.name == 'nt':
    # Explicit termination avoids testing CRT/DLL teardown as part of the
    # functional assertions. The limitation is recorded above, never hidden.
    import ctypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.TerminateProcess.argtypes=[ctypes.c_void_p,ctypes.c_uint]
    kernel.TerminateProcess.restype=ctypes.c_int
    if not kernel.TerminateProcess(kernel.GetCurrentProcess(),code):
        raise OSError(ctypes.get_last_error(),'Impossible de terminer le processus de réception')
else:
    os._exit(code)
