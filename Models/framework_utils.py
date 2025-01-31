import pandas as pd
import numpy as np
import json, time, os, sys, gc

from scipy import stats
from IPython.display import clear_output

import numerapi

def percFin(iterator,listlen,rounded=3):
    clear_output(wait=True)
    print("Processing.. ",round(((iterator+1)/listlen) * 100,rounded),'%',flush=True)

def rank01(arr):
    arr = stats.rankdata(arr, method="average")
    arr = arr - 0.5
    return arr / len(arr)

def colrank01(arrs):
    return np.apply_along_axis(rank01,0,arrs)

def erarank01(arrs, I):
    arrsc = arrs.copy()
    if len(arrs.shape) == 2:
        for E in range(len(I)):
            arrsc[I[E]] = np.apply_along_axis(rank01,0,arrs[I[E]])
    else:
        for E in range(len(I)):
            arrsc[I[E]] = rank01(arrs[I[E]])
    return arrsc


def get_numerapi_config():
    # load id and key from json if exists, else create new file
    if not os.path.exists('config.json'):
        # create template json file
        with open('config.json', 'w') as f:
            json.dump({'id':'', 'key':''}, f)
        print('Please enter your Numerai ID and Key in created config.json and restart')
        time.sleep(5)
        sys.exit()
    else:
        with open('config.json', 'r') as f:
            config = json.load(f)
        if config['id'] == '' or config['key'] == '':
            print('Please enter your Numerai ID and Key in config.json and restart')
            time.sleep(5)
            exit()
        else:
            public_id = config['id']
            secret_key = config['key']
            print('numerapi ID and Key loaded from config.json')
            return public_id, secret_key
        
def get_napi_and_models(public_id, secret_key):
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
                exit(); # maybe add some email notification here?
            print("NumerAPI connection failed, retrying...")
            time.sleep(5)
    return napi, modelnameids


train_files = [
    'train.parquet', 'validation.parquet',
         'validation_example_preds.parquet', 'validation_benchmark_models.parquet',
         'features.json', 
        #  'meta_model.parquet'
         ] 

live_files = ['live.parquet', 'live_example_preds.parquet',
               'features.json', 'live_benchmark_models.parquet']

def chk_depreciate_ds(ds_file, dataset_loc):
    fp = os.path.join(dataset_loc, ds_file)
    if os.path.exists(fp):
        os.rename(fp, fp+'.old')

def chk_reinstate_ds(ds_file, dataset_loc):
    fp = os.path.join(dataset_loc, ds_file)
    if os.path.exists(fp+'.old'):
        os.rename(fp+'.old', fp)

def chk_rm_ds(ds_file, dataset_loc):
    fp = os.path.join(dataset_loc, ds_file)
    if os.path.exists(fp): os.remove(fp)

def get_update_data(napi, dataset_loc, ds_version, files):
    if not os.path.exists(dataset_loc):
        os.makedirs(dataset_loc)
        print('Created dataset directory at', dataset_loc)
    
    currentRound = napi.get_current_round()
    # check if txt file is there
    if not os.path.exists(os.path.join(dataset_loc, 'lastRoundAcq.txt')):
        with open(os.path.join(dataset_loc,'lastRoundAcq.txt'), 'w') as f:
            f.write('0')
        print('Created lastRoundAcq.txt')
    with open(os.path.join(dataset_loc, 'lastRoundAcq.txt'), 'r') as f:
        lastRound = int(f.read())
    any_data_failure = False
    newRound = lastRound != currentRound
    if newRound:
        print('Dataset not up to date, retrieving dataset... ',end='')
        for ds_file in files: 
            if currentRound - lastRound > 5 or 'train' not in ds_file: # avoid redownloading train too often
                chk_depreciate_ds(ds_file, dataset_loc)
        print('done')
        print('downloading new files... ',end='')
        for ds_file in files: 
            if currentRound - lastRound > 5 or 'train' not in ds_file:
                napi_success = False; loops = 0
                while not napi_success:
                    try:
                        napi.download_dataset(ds_version+'/'+ds_file, 
                                            os.path.join(dataset_loc,ds_file))
                        napi_success = True
                    except:
                        loops += 1
                        if loops > 5:
                            print('Numerapi data download failed, reverting to old file.')
                            chk_reinstate_ds(ds_file, dataset_loc)
                            any_data_failure = True
                            break
                        print('Numerapi data download error, retrying...')
                        time.sleep(5)
                if napi_success:
                    chk_rm_ds(ds_file+'.old', dataset_loc)
        print('done')
        clear_output()
        if not any_data_failure: # if any data failed, don't update lastRoundAcq, so it will try again next time
            with open(dataset_loc + '/lastRoundAcq.txt', 'w') as f:
                f.write(str(currentRound))
            print("Datasets are up to date.\nCurrent Round:", currentRound)
        else:
            print("Some Datasets failed to update, submissions may fail.\nCurrent Round:", currentRound)
    return currentRound, newRound

def get_update_training_data(napi, dataset_loc, ds_version):
    return get_update_data(napi, dataset_loc, ds_version, train_files)

def get_update_live_data(napi, dataset_loc, ds_version):
    return get_update_data(napi, dataset_loc, ds_version, live_files)


def processData(df_loc, return_target_names=False):
    df = pd.read_parquet(df_loc, engine="fastparquet")
    E = df['era'].values; uE = pd.unique(E)
    I = [(np.arange(len(E), dtype=np.int64)[x==E]) for x in uE]
    # features = [f for f in list(df.iloc[0].index) if "feature" in f]
    targets = [f for f in list(df.iloc[0].index) if "target" in f]
    # df = df[features+targets]; df = df.to_numpy(dtype=np.float16, na_value=0.5)
    # X = df[:,:-len(targets)]; Y = df[:,-len(targets):]; del df; gc.collect()
    if return_target_names: 
        return df, I, targets
    else:
        return df, I


def submitPredictions(LP, Model, modelids, liveids, currentRound, napi, verbose=2):
    name = Model.name
    sub_names = Model.submit_on
    if type(sub_names) != list: 
        sub_names = [sub_names]; LP = LP.reshape(-1, 1)
    elif len(LP.shape) == 1:
        LP = LP.reshape(-1, 1)
    print('building predictions for', name, sub_names)

    submissions = {}
    response_keys = {}

    for i in range(len(sub_names)):
        upload = sub_names[i]
        results_df = pd.DataFrame(data={'prediction' : LP[:,i]})
        joined = pd.DataFrame(liveids, columns=['id']).join(results_df)
        if verbose > 1: print(joined.head(3))

        subName = "submission_"+name+"_"+upload+"_"+str(currentRound)+".csv"
        if verbose > 0: print("# Writing predictions to "+subName+"... ",end="")
        joined.to_csv("Submissions/"+subName, index=False)
        upload_key = None
        if not len(upload) > 0:
            if verbose > 1: print("No upload for these predictions. (may be base model)")
        else:
            napi_success = False; loops = 0
            while not napi_success:
                try:
                    upload_key = napi.upload_predictions("Submissions/"+subName, 
                                                    model_id=modelids[upload])
                    napi_success = True
                except:
                    loops += 1
                    if loops >= 5:
                        print("Failed to upload predictions for "+upload)
                        # remove failed submission file
                        os.remove("Submissions/"+subName)
                        break
                    print("Upload for "+upload+" failed, retrying... ",end="")
                    time.sleep(4)
            if verbose > 0: print(upload_key)
        submissions[upload] = LP[:,i]
        response_keys[upload] = upload_key
        if verbose > 1: print("done")
    return submissions, response_keys


def get_currentRound_submissions(currentRound, modelmodules, avoid_resubmissions=True):
    submissions = {}
    if not os.path.exists('Submissions'): 
        os.makedirs('Submissions')
    else:
        sub_files = os.listdir('Submissions')
        sub_files = [x for x in sub_files if str(currentRound) in x and 'submission' in x]
        sub_names = [x.split('_')[1:-1] for x in sub_files]
        for i in range(len(sub_names)):
            sub_name = sub_names[i]
            model_name, upload_name = sub_name[0], sub_name[1]
    
            d = pd.read_csv('Submissions\\'+sub_files[i], header=0).values[:,1].astype(float)
            submissions[upload_name] = d
        
    if avoid_resubmissions:
        remove = []
        for model in modelmodules:
            if all([upload_name in submissions.keys() for upload_name in model.submit_on]):
                remove.append(model)
        for model in remove:
            modelmodules.remove(model)
    return submissions, modelmodules


def get_validation_predictions():
    predictions = {}
    if not os.path.exists('Validations'): 
        os.makedirs('Validations')
    else:
        sub_files = os.listdir('Validations')
        sub_files = [x for x in sub_files if 'validation' in x]
        sub_names = [x.split('_')[1:] for x in sub_files]
        for i in range(len(sub_names)):
            sub_name = sub_names[i]
            model_name, upload_name = sub_name[0], sub_name[1]
    
            d = pd.read_csv('Submissions\\'+sub_files[i], header=0).values[:,1].astype(float)
            predictions[sub_name] = d
    return predictions


def saveValidationPredictions(P, Model, ids, verbose=2):
    name = Model.name
    sub_names = Model.submit_on
    if type(sub_names) != list: 
        sub_names = [sub_names]; P = P.reshape(-1, 1)
    elif len(P.shape) == 1:
        P = P.reshape(-1, 1)
    print('saving validation predictions for', name, sub_names)

    predictions = {}

    for i in range(len(sub_names)):
        upload = sub_names[i]
        results_df = pd.DataFrame(data={'prediction' : P[:,i]})
        joined = pd.DataFrame(ids, columns=['id']).join(results_df)
        if verbose > 1: print(joined.head(3))

        subName = "validation_"+name+"_"+upload+".csv"
        if verbose > 0: print("# Writing predictions to "+subName+"... ",end="")
        joined.to_csv("Validations/"+subName, index=False)
        predictions[upload] = joined
        if verbose > 1: print("done")

    return predictions