"""Replay the same six drafts with one repair, two additions and a shared retry."""
import argparse
from pathlib import Path
from experiments.verify_additive_length import run
from relation_pipeline.common import ROOT

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'runs/smoke_legacy_short_20261004_v1')
    args=parser.parse_args()
    run(args.run_id,args.source,'separated_v1')
