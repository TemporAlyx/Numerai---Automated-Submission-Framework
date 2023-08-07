import pandas as pd
import numpy as np
import time, os, sys, gc, json

os.chdir(os.path.dirname(os.path.abspath(__file__)))

from Models.framework_utils import *

# load numerapi
public_id, secret_key = get_numerapi_config()
import numerapi
napi = None
modelnameids = None
napi_success = False; loops = 0
while not napi_success:
    try:
        napi = numerapi.NumerAPI(public_id=public_id, secret_key=secret_key)
        modelnameids = napi.get_models()
        napi_success = True
    except:
        loops += 1
        if loops > 10:
            print("NumerAPI connection failed, exiting...")
            sys.exit(); # maybe add some email notification here?
        print("NumerAPI connection failed, retrying...")
        time.sleep(5)

# load data
ds_version = "v4.1"
dataset_loc = os.path.join(os.getcwd(), 'live_datasets', ds_version)
currentRound = get_update_live_data(napi, dataset_loc)

np.random.seed(42)
print("# Loading data... ",end='')

# live submission data L* | X = features, P = prediction, I = era indices
LX, _, LI, features, targets = processData(os.path.join(dataset_loc, 'live.parquet'), return_fts=True)

with open(os.path.join(dataset_loc, "features.json"), "r") as f:
    feature_metadata = json.load(f)
    
small_features = np.arange(len(features))[np.isin(features,feature_metadata['feature_sets']['small'])]
medium_features = np.arange(len(features))[np.isin(features,feature_metadata['feature_sets']['medium'])]

ELP = pd.read_parquet(os.path.join(dataset_loc, 'live_example_preds.parquet'), engine="fastparquet")
ids = ELP.index.values
ELP = ELP.values[:,0]

gc.collect()
print("done")


import Models

submissions = {}
upload_keys = {}
EMods = []

submissions['example_model'] = ELP

model_modules = Models.models

n_submissions, model_modules = get_currentRound_submissions(
    currentRound, modelnameids, model_modules
)
submissions.update(n_submissions)

Mods = [Models.__dict__[x].CustomModel for x in model_modules]
print(model_modules)


def build_and_submit_model(Model):
    if Model.ensembled:
        LP = Model.predict(LX, LI, features, submissions)
    else:
        LP = Model.predict(LX, LI, features)
    LP = erarank01(LP, LI)

    n_submissions, n_response_keys = submitPredictions(
        LP, Model, modelnameids, ids, currentRound, napi
    )
    if len(n_submissions) > 0:
        submissions.update(n_submissions)
        upload_keys.update(n_response_keys)

for Model in Mods:
    if Model.ensembled:
        EMods.append(Model) # wait until other models are done for ensembles
    else:
        build_and_submit_model(Model)

for Model in EMods:
    build_and_submit_model(Model)