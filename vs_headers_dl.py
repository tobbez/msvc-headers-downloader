#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import requests
import shutil
import subprocess
import time
import urllib.parse
import zipfile

from pathlib import Path

import msi

def parse_version(v):
  return [int(x) for x in v.split('.')]

def find_manifest(channel):
  for i in channel['channelItems']:
    if i['id'] == 'Microsoft.VisualStudio.Manifests.VisualStudio':
      return i

def select_sdk_package(manifest):
  sdks = [p for p in manifest['packages'] if p['id'].startswith('Win10SDK_')]
  sdks.sort(key=lambda x: parse_version(x['version']), reverse=True)
  return sdks[0]

def find_sdk_headers_msi(sdk):
  for p in sdk['payloads']:
    if p['fileName'].endswith('\\Windows SDK Desktop Headers x86-x86_en-us.msi'):
      return p

def get_cabs_for_msi(path):
  m = msi.MSI(str(path))
  return [r['Cabinet'] for r in m.query('SELECT Cabinet FROM Media WHERE Cabinet IS NOT NULL')]

def filter_sdk_cabs(sdk, cabs):
  cabs = set(cabs)
  for p in sdk['payloads']:
    if p['fileName'].rsplit('\\')[-1] in cabs:
      yield p

def filter_vsix_packages(manifest, vsix_pkgs):
  vsix_pkg_set = set(vsix_pkgs)
  found = [p for p in manifest['packages'] if p['id'] in vsix_pkg_set]
  return [v['payloads'][0] for v in sorted(found, key=lambda p: vsix_pkgs.index(p['id']))]

def find_universal_crt_package(manifest):
  for p in manifest['packages']:
    if p['id'] == 'Microsoft.Windows.UniversalCRT.HeadersLibsSources.Msi':
      return p

def find_universal_crt_msi(package):
  for p in package['payloads']:
    if p['fileName'].endswith('\\Universal CRT Headers Libraries and Sources-x86_en-us.msi'):
      return p

#def find_universal_crt_msi(package):
#  for p in package['payloads']:
#    if p['fileName'] == 'Universal CRT Headers Libraries and Sources-x86_en-us.msi':
#      return p

def filter_package_msis(package, msis):
  msi_set = set(msis)
  found = []
  for p in package['payloads']:
    if p['fileName'].rsplit('\\')[-1] in msi_set:
      found.append(p)
  return sorted(found, key=lambda p: msis.index(p['fileName'].rsplit('\\')[-1]))


def extract_msi(msi, path):
  print(f'Extracting "{msi.name}"...', end='', flush=True)
  proc = subprocess.run(['msiextract', '-C', str(path), str(msi)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, encoding='utf-8')

  # msiextract is badly behaved and doesn't exit with an error code on error,
  # so check if it wrote to stderr instead
  if len(proc.stderr) > 0:
    print(' Failed! msiextract stderr:')
    print(proc.stderr)
  else:
    print(' OK')

def extract_vsix(vsix, path):
  print(f'Extracting "{vsix.name}"...', end='', flush=True)
  with zipfile.ZipFile(vsix) as zf:
    zf.extractall(path)
  print(' OK')

class Downloader:
  def __init__(self):
    self.arg_parser = argparse.ArgumentParser()
    self.arg_parser.add_argument('--channel', default='https://aka.ms/vs/16/release/channel')
    self.arg_parser.add_argument('output_dir', metavar='output-dir', type=Path)

    self.session = requests.Session()
    self.session.headers['User-Agent'] = 'VS headers downloader'

  def handle_args(self):
    self.args = self.arg_parser.parse_args()
    self.download_dir = self.args.output_dir / 'download'
    self.extracted_dir = self.args.output_dir / 'extracted'

  def download_json(self, url, name=None):
    print(f'Downloading {url}...', end='', flush=True)

    if name is None:
      name = os.path.basename(urllib.parse.urlparse(url).path)
    if name == '':
      raise Exception(f'Attempted to download to invalid file name "{name}"')

    local_path = (self.download_dir / name)

    try:
      with local_path.open() as f:
        d = json.load(f)
        print(' Cached')
        return d
    except OSError as e:
      pass

    r = self.session.get(url).json()

    local_path.parent.mkdir(parents=True, exist_ok=True)
    with local_path.open('w') as f:
      json.dump(r, f)

    print(' OK')

    return r

  def download_binary(self, payload):
    """
    payload dict as present in the manifest
    """
    local_path = self.download_dir / payload['fileName'].replace('\\', '/')

    print(f'Downloading {payload["url"]}...', end='', flush=True)

    try:
      with local_path.open('rb') as f:
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(512*1024), b''):
          h.update(chunk)
      if h.hexdigest().lower() == payload['sha256'].lower():
        print(' Cached')
        return local_path
    except OSError as e:
      pass

    class DownloadError(Exception):
      pass

    local_path.parent.mkdir(parents=True, exist_ok=True)

    for try_number in range(3):
      try:
        dl = self.session.get(payload['url'], stream=True)

        dl.raise_for_status()

        h = hashlib.sha256()

        with local_path.open('wb') as f:
          for chunk in dl.iter_content(512*1024):
            h.update(chunk)
            f.write(chunk)

        if h.hexdigest().lower() != payload['sha256'].lower():
          raise DownloadError('Hash check failed')

        break

      except (requests.exceptions.ConnectionError, DownloadError) as e:
        print(' Failed')
        print('Retrying...', end='', flush=True)
        if local_path.exists():
          local_path.rename(local_path.with_name(local_path.name + '.failed'))
        time.sleep(3)
    else:
      print('Download failed after retries')
      raise SystemExit(1)

    print(' OK')
    return local_path

  def download_msi_cabs(self, msi_path, package):
    cabs = get_cabs_for_msi(msi_path)
    for c in filter_sdk_cabs(package, cabs):
      self.download_binary(c)

  def extract_all(self):
    try:
      shutil.rmtree(self.extracted_dir)
    except FileNotFoundError:
      pass

    self.extracted_dir.mkdir(parents=True, exist_ok=True)

    msis = list(self.download_dir.rglob('*.msi'))
    vsixes = list(self.download_dir.rglob('*.vsix'))

    for m in msis:
      extract_msi(m, self.extracted_dir)

    for v in vsixes:
      extract_vsix(v, self.extracted_dir)

  def run(self):
    self.handle_args()

    self.download_dir.mkdir(parents=True, exist_ok=True)

    channel = self.download_json(self.args.channel)

    manifest_item = find_manifest(channel)
    manifest = self.download_json(manifest_item['payloads'][0]['url'])

    sdk = select_sdk_package(manifest)

    msi_names = [
        'Windows SDK Desktop Headers x86-x86_en-us.msi',
        'Windows SDK Desktop Headers x64-x86_en-us.msi',

        'Windows SDK Desktop Libs x86-x86_en-us.msi',
        'Windows SDK Desktop Libs x64-x86_en-us.msi',

        'Universal CRT Headers Libraries and Sources-x86_en-us.msi',

        'Windows SDK for Windows Store Apps Headers-x86_en-us.msi',
        'Windows SDK for Windows Store Apps Libs-x86_en-us.msi',
    ]

    for m in filter_package_msis(sdk, msi_names):
      path = self.download_binary(m)
      self.download_msi_cabs(path, sdk)

    vsix_dist_ids = [
        'Microsoft.VisualCpp.CRT.Headers',
        'Microsoft.VisualCpp.CRT.x64.Desktop',
        'Microsoft.VisualCpp.CRT.x86.Desktop',
        'Microsoft.VisualCpp.CRT.x86.Store',
        'Microsoft.VisualCpp.CRT.x64.Store',
    ]

    for vp in filter_vsix_packages(manifest, vsix_dist_ids):
      self.download_binary(vp)

    self.extract_all()


if __name__ == '__main__':
  Downloader().run()
