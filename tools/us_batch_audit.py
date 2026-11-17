import json, traceback
import pandas as pd
import yfinance as yf
from src import main as m
print("VERSIONS:"+json.dumps({"pandas":pd.__version__,"yfinance":yf.__version__}),flush=True)
original_download = yf.download
def traced_download(*args, **kwargs):
    frame = original_download(*args, **kwargs)
    print("ACTUAL_FRAME:"+json.dumps({"empty":frame.empty,"shape":frame.shape,"columns":[str(c) for c in frame.columns],"column_names":list(frame.columns.names),"tail":frame.tail(2).to_json(date_format="iso")}),flush=True)
    return frame
original_history = m._history_prices
def traced_history(*args, **kwargs):
    try:
        return original_history(*args, **kwargs)
    except Exception as error:
        print("HISTORY_ERROR:"+json.dumps({"type":type(error).__name__,"message":str(error),"traceback":traceback.format_exc(limit=5)}),flush=True)
        raise
m.yf.download=traced_download
m._history_prices=traced_history
for symbols in (["SPY","SOXX"], ["SPY"]):
    result=m.dl(symbols,"1y",chunk=2,sleep=0)
    print("ACTUAL_DL:"+json.dumps({"symbols":symbols,"returned":list(result),"lengths":{k:len(v) for k,v in result.items()}}),flush=True)
