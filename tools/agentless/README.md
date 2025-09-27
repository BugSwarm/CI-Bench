# Evaluations on the Effectiveness of LM Tools with CI-Bench 

We will test the efficacy of Agentless(CIFailureFix version) using `tananaev-traccar-64783123` as an example artifact. It is a Java artifact and from github, we come to know its diff size is 2.

# Setting up the Agentless

1. Clone the repository
```bash
git clone https://github.com/BugSwarm/CIFailureFix-Agent.git
```

2. Go inside `CIFailureFix-Agent/Agentless`
```bash
cd CIFailureFix-Agent/Agentless
```

3. Run
```bash
conda create -n agentless python=3.11 
conda activate agentless
pip install -r requirements.txt
export PYTHONPATH=$PYTHONPATH:$(pwd)
```
at the repository root (as with any python setup, it's recommended to use conda or virtual environments to manage dependencies).

3. Export the OPENAI_KEY/ANTHROPIC_API_KEY
```bash
export OPENAI_API_KEY={key_here}
export ANTHROPIC_API_KEY={key_here}
```

4. Export the bugswarm token
```bash
export BUGSWARM_TOKEN={key_here}
```

# Running python script for generating the patch

1. Go into Agentless folder
```bash
cd CIFailureFix-Agent/Agentless
```

2. For localize
```bash
python3 agentless/fl/localize.py --file_level --related_level --fine_grain_line_level --output_folder <location_folder> --top_n <n_files> --compress --context_window=<window_size> --bugswarm_image <bugswarm_image_tag> --model <llm_model_name> --backend <api_type> --language <language>
```
Here,
- `output_folder`: saved file-level localization in the folder
- `top_n`: the number of files we want to consider
- `context_window`: the number of files we want to consider
- `bugswarm_image`: bugswarm artifact
- `model`: llm model
- `language`: java/python
- `backend`: openai/anthropic

For BugSwarm image we are using `tananaev-traccar-64783123`

if we want to use `gpt-4o-2024-05-13`, 
command will be
```bash
python3 agentless/fl/localize.py --file_level --related_level --fine_grain_line_level --output_folder results/location --top_n 3 --compress --context_window=10 --bugswarm_image tananaev-traccar-64783123 --model gpt-4o-2024-05-13 --backend openai --language java
```

location output will be saved at `results/location/loc_outputs.jsonl`

3. For repair 
```bash
python3 agentless/repair/repair.py --loc_file <output_location_jsonl> --output_folder <output_folder> --top_n=<n_files> --context_window=<window_size> --max_samples <sample_patches>  --cot --diff_format --gen_and_process --model <llm_model> --backend <api_type> --language <language> --patch_folder <patch_dir>
```    
We can vary the number of `max_samples` and all the patches will be saved in patch folder
```bash
python3 agentless/repair/repair.py --loc_file results/location/loc_outputs.jsonl --output_folder results/repair--loc_interval --top_n=3 --context_window=10 --max_samples 10  --cot --diff_format --gen_and_process --model gpt-4o-2024-05-13 --backend openai --language java --patch_folder patches
``` 

The generated patch is stored in `patches` and they are named as `patch_0.patch`, `patch_1.patch` ... etc

```
diff --git a/src/org/traccar/protocol/CastelProtocolDecoder.java b/src/org/traccar/protocol/CastelProtocolDecoder.java
index 75021d3..4df1f7d 100644
--- a/src/org/traccar/protocol/CastelProtocolDecoder.java
+++ b/src/org/traccar/protocol/CastelProtocolDecoder.java
@@ -89,13 +89,16 @@ public class CastelProtocolDecoder extends BaseProtocolDecoder {
                     response.writeShort(ChannelBuffers.swapShort(MSG_LOGIN_RESPONSE));
                     response.writeInt(0xFFFFFFFF);
                     response.writeShort(0);
+                if (response != null && channel != null && remoteAddress != null) {
                     response.writeInt((int) (new Date().getTime() / 1000));
+
                     response.writeShort(Crc.crc16Ccitt(response.toByteBuffer(0, response.writerIndex())));
                     response.writeByte(0x0D); response.writeByte(0x0A);
                     channel.write(response, remoteAddress);
                 }
-            
             }
+        }
+
             
             if (type == MSG_GPS) {
                 buf.readUnsignedByte(); // historical
@@ -140,4 +143,4 @@ public class CastelProtocolDecoder extends BaseProtocolDecoder {
         return null;
     }
 
-}
+}


```

```
diff --git a/src/org/traccar/protocol/CastelProtocolDecoder.java b/src/org/traccar/protocol/CastelProtocolDecoder.java
index 75021d3..1abe775 100644
--- a/src/org/traccar/protocol/CastelProtocolDecoder.java
+++ b/src/org/traccar/protocol/CastelProtocolDecoder.java
@@ -82,7 +82,9 @@ public class CastelProtocolDecoder extends BaseProtocolDecoder {
 
                 if (channel == null) {
                     ChannelBuffer response = ChannelBuffers.directBuffer(ByteOrder.LITTLE_ENDIAN, 41);
+                if (channel != null && remoteAddress != null) {
                     response.writeByte(0x40); response.writeByte(0x40);
+
                     response.writeShort(response.capacity());
                     response.writeByte(version);
                     response.writeBytes(id);
@@ -94,15 +96,24 @@ public class CastelProtocolDecoder extends BaseProtocolDecoder {
                     response.writeByte(0x0D); response.writeByte(0x0A);
                     channel.write(response, remoteAddress);
                 }
+
+                }
             
             }
             
-            if (type == MSG_GPS) {
+            if (buf != null && type == MSG_GPS) {
+
                 buf.readUnsignedByte(); // historical
             }
             
-            buf.readUnsignedInt(); // ACC ON time
-            buf.readUnsignedInt(); // UTC time
+            if (buf != null) {
+                buf.readUnsignedInt(); // ACC ON time
+            }
+
+            if (buf != null) {
+                buf.readUnsignedInt(); // UTC time
+            }
+
             position.set(Event.KEY_ODOMETER, buf.readUnsignedInt());
             buf.readUnsignedInt(); // trip odometer
             buf.readUnsignedInt(); // total fuel consumption
@@ -140,4 +151,4 @@ public class CastelProtocolDecoder extends BaseProtocolDecoder {
         return null;
     }
 
-}
+}
```

# Testing the patch generated by CIFailureFix-Agent(optional):

We will test the generated patch with our hands. Let's follow the steps:

1. Go into `CIFailureFix-Agent` folder

```bash
cd <path_to_CIFailureFix-Agent>
```


2. We have to find out the container id using this

```bash
docker ps -a
```

After executing this, we will get a list of the containers running. We have to find the id using BugSwarm image name

3. Copy the `repo_reset.sh` file into that container

```bash
docker cp repo_reset.sh <container_id>:/home/travis/
```

4. After getting the container id, we will enter into the container

```bash
docker exec -it <container_id> /bin/bash
```

5. Change mode for the script `repo_reset.sh` and execute it.
```bash
chmod +x repo_reset.sh
./repo_reset.sh <build_system> <folder1> <folder2>
```
for the tutorial, we are using `travis` build system, folder1 will be `tananaev`, folder2 will be `traccar`. So the command will be

```bash
./repo_reset.sh travis tananaev traccar
```


6. Enter into the path `/home/travis/build/failed/tananaev/traccar`

```bash
cd /home/travis/build/failed/tananaev/traccar
```

7. Apply the patch on the folder

```bash
cp /home/travis/model.patch /home/travis/build/failed/tananaev/traccar/
git apply model.patch
```

8. Run the script to build the repo to see if the build process is successful 

```bash
cd /usr/local/bin
./run_failed.sh
```