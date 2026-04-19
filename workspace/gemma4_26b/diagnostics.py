import sys
import os
import json

data = {
    'sys_path': sys.path,
    'cwd': os.getcwd(),
    'python_version': sys.version,
}

try:
    import youtube_transcript_api
    data['api_file'] = youtube_transcript_api.__file__
    try:
        data['api_attrs'] = dir(youtube_transcript_api.YouTubeTranscriptApi)
    except Exception as e:
        data['api_attr_error'] = str(e)
except Exception as e:
    data['api_import_error'] = str(e)

with open('workspace/gemma4_26b/diagnostic_results.json', 'w') as f:
    json.dump(data, f, indent=2)
