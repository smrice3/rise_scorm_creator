import streamlit as st
import xml.etree.ElementTree as ET
import os
import shutil
import zipfile
import tempfile
import uuid
from datetime import datetime
import base64
import io

st.set_page_config(page_title="SCORM Package Generator", page_icon="📚", layout="wide")

st.title("Rise TinCan to SCORM Package Converter")
st.write("This app converts a Rise TinCan XML file into a SCORM 1.2 package.")

# File uploader for tincan.xml
uploaded_file = st.file_uploader("Upload your tincan.xml file", type=["xml"])

# Base URL input
base_url = st.text_input("Enter the base URL for the Rise content (without /index.html):", 
                         placeholder="e.g., https://example.com/rise-content")

def extract_activities(xml_content):
    """Extract activities marked as blocks and sections from tincan XML"""
    root = ET.fromstring(xml_content)
    
    # Define namespaces
    namespaces = {
        'tincan': 'http://projecttincan.com/tincan.xsd',
        'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'xsd': 'http://www.w3.org/2001/XMLSchema'
    }
    
    activities = []
    
    # Find all activities
    for activity in root.findall('.//tincan:activity', namespaces):
        activity_id = activity.get('id')
        activity_type = activity.get('type')
        
        # Get name and check if it's a block or section
        name_elem = activity.find('./tincan:name', namespaces)
        if name_elem is not None:
            name = name_elem.text
            
            # Check if name ends with /blocks or /section
            is_block = name.endswith('/blocks')
            is_section = name.endswith('/section')
            
            if is_block or is_section:
                # Extract the ID part from the full activity ID
                lesson_id = activity_id.split('/')[-1]
                
                # Get description
                description_elem = activity.find('./tincan:description', namespaces)
                description = description_elem.text if description_elem is not None else ""
                
                # Clean up name by removing the /blocks or /section suffix
                clean_name = name.replace('/blocks', '').replace('/section', '')
                
                activities.append({
                    'id': lesson_id,
                    'full_id': activity_id,
                    'name': clean_name,
                    'description': description,
                    'type': 'block' if is_block else 'section'
                })
    
    return activities

def get_course_info(xml_content):
    """Extract course title and description from tincan XML"""
    root = ET.fromstring(xml_content)
    
    namespaces = {
        'tincan': 'http://projecttincan.com/tincan.xsd',
        'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'xsd': 'http://www.w3.org/2001/XMLSchema'
    }
    
    # Find the course activity (first activity of type course)
    course_activity = root.find('.//tincan:activity[@type="http://adlnet.gov/expapi/activities/course"]', namespaces)
    
    if course_activity is not None:
        name_elem = course_activity.find('./tincan:name', namespaces)
        desc_elem = course_activity.find('./tincan:description', namespaces)
        
        course_title = name_elem.text if name_elem is not None else "Untitled Course"
        course_description = desc_elem.text if desc_elem is not None else ""
        
        return {
            'title': course_title,
            'description': course_description
        }
    
    return {'title': "Untitled Course", 'description': ""}

def create_html_page(lesson_id, lesson_title, base_url):
    """Create an HTML page with an iframe pointing to the Rise content"""
    
    # This HTML template includes SCORM 1.2 API calls
    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{lesson_title}</title>
    <style>
        body, html {{
            margin: 0;
            padding: 0;
            height: 100%;
            overflow: hidden;
        }}
        .container {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }}
        iframe {{
            width: 100%;
            height: 100%;
            border: none;
        }}
    </style>
    <script>
        var apiHandle = null;
        var lessonStatus = "incomplete";
        var startTimeStamp = "";
        var exitPageStatus = "suspended";
        
        function getAPIHandle() {{
            if (apiHandle == null) {{
                apiHandle = getAPI();
            }}
            return apiHandle;
        }}
        
        function getAPI() {{
            var theAPI = findAPI(window);
            if ((theAPI == null) && (window.opener != null) && (typeof(window.opener) != "undefined")) {{
                theAPI = findAPI(window.opener);
            }}
            if (theAPI == null) {{
                console.log("Unable to find an API adapter");
            }}
            return theAPI;
        }}
        
        function findAPI(win) {{
            var findAPITries = 0;
            while ((win.API == null) && (win.parent != null) && (win.parent != win)) {{
                findAPITries++;
                if (findAPITries > 500) {{
                    console.log("Error finding API -- too deeply nested.");
                    return null;
                }}
                win = win.parent;
            }}
            return win.API;
        }}
        
        function initializeCommunication() {{
            var api = getAPIHandle();
            if (api == null) {{
                console.log("No API found.");
                return "false";
            }}
            
            var result = api.LMSInitialize("");
            if (result != "true") {{
                var errorNumber = api.LMSGetLastError();
                var errorString = api.LMSGetErrorString(errorNumber);
                var diagnostic = api.LMSGetDiagnostic(errorNumber);
                console.log("Error initializing communication with the LMS: " + errorString);
                return "false";
            }}
            
            return "true";
        }}
        
        function terminateCommunication() {{
            var api = getAPIHandle();
            if (api == null) {{
                console.log("No API found.");
                return "false";
            }}
            
            var result = api.LMSFinish("");
            if (result != "true") {{
                var errorNumber = api.LMSGetLastError();
                var errorString = api.LMSGetErrorString(errorNumber);
                var diagnostic = api.LMSGetDiagnostic(errorNumber);
                console.log("Error terminating communication with the LMS: " + errorString);
                return "false";
            }}
            
            return "true";
        }}
        
        function recordCompletionStatus(status) {{
            var api = getAPIHandle();
            if (api == null) {{
                console.log("No API found.");
                return "false";
            }}
            
            var result = api.LMSSetValue("cmi.core.lesson_status", status);
            if (result != "true") {{
                var errorNumber = api.LMSGetLastError();
                var errorString = api.LMSGetErrorString(errorNumber);
                var diagnostic = api.LMSGetDiagnostic(errorNumber);
                console.log("Error setting lesson status: " + errorString);
                return "false";
            }}
            
            return "true";
        }}
        
        window.onload = function() {{
            initializeCommunication();
            startTimeStamp = new Date();
            recordCompletionStatus("incomplete");
        }};
        
        window.onbeforeunload = function() {{
            var endTimeStamp = new Date();
            var totalTimeSpent = (endTimeStamp - startTimeStamp) / 1000;
            
            var api = getAPIHandle();
            if (api != null) {{
                api.LMSSetValue("cmi.core.session_time", formatTime(totalTimeSpent));
                api.LMSCommit("");
            }}
            
            recordCompletionStatus(exitPageStatus);
            terminateCommunication();
        }};
        
        function formatTime(totalSeconds) {{
            var hours = Math.floor(totalSeconds / 3600);
            var minutes = Math.floor((totalSeconds - hours * 3600) / 60);
            var seconds = Math.floor(totalSeconds - hours * 3600 - minutes * 60);
            
            var formattedTime = "";
            if (hours > 0) {{
                formattedTime += hours + ":";
            }}
            
            if (minutes < 10 && hours > 0) {{
                formattedTime += "0";
            }}
            formattedTime += minutes + ":";
            
            if (seconds < 10) {{
                formattedTime += "0";
            }}
            formattedTime += seconds;
            
            return formattedTime;
        }}
        
        function markAsComplete() {{
            exitPageStatus = "completed";
            recordCompletionStatus("completed");
            alert("This lesson has been marked as complete.");
        }}
    </script>
</head>
<body>
    <div class="container">
        <iframe src="{base_url}/index.html#/lessons/{lesson_id}" allowfullscreen></iframe>
    </div>
    <div style="position: absolute; bottom: 10px; right: 10px; z-index: 1000;">
        <button onclick="markAsComplete()" style="padding: 10px; background-color: #4CAF50; color: white; border: none; border-radius: 5px; cursor: pointer;">
            Mark as Complete
        </button>
    </div>
</body>
</html>
"""
    
    return html_template

def create_imsmanifest(course_title, activities, org_identifier):
    """Create the imsmanifest.xml file content with hierarchical structure"""
    
    # Group activities by section (if they have a parent-child relationship)
    sections = {}
    standalone_activities = []
    
    # First, identify sections
    for activity in activities:
        if activity['type'] == 'section':
            sections[activity['id']] = {
                'info': activity,
                'children': []
            }
    
    # Then, assign activities to sections or standalone list
    for activity in activities:
        if activity['type'] == 'block':
            # Try to find a parent section
            parent_found = False
            for section_id, section_data in sections.items():
                # This is a simple way to check if an activity belongs to a section
                # You might need a more sophisticated approach depending on your data structure
                if activity['name'].startswith(section_data['info']['name']):
                    section_data['children'].append(activity)
                    parent_found = True
                    break
            
            if not parent_found:
                standalone_activities.append(activity)
    
    # Create resources XML
    resources_xml = ""
    
    # Add each activity as a resource
    for activity in activities:
        resources_xml += f"""
        <resource identifier="resource_{activity['id']}" type="webcontent" adlcp:scormtype="sco" href="{activity['id']}.html">
            <file href="{activity['id']}.html"/>
        </resource>"""
    
    # Create items XML with hierarchy
    items_xml = ""
    
    # Add sections with their children
    for section_id, section_data in sections.items():
        section = section_data['info']
        children = section_data['children']
        
        # Only create a section if it has children or is a standalone section
        if children or section_id in [a['id'] for a in standalone_activities]:
            section_items = ""
            
            # Add children items
            for child in children:
                section_items += f"""
                <item identifier="item_{child['id']}" identifierref="resource_{child['id']}">
                    <title>{child['name']}</title>
                </item>"""
            
            # Create the section item with children
            items_xml += f"""
            <item identifier="item_{section['id']}"{' identifierref="resource_' + section['id'] + '"' if section_id in [a['id'] for a in standalone_activities] else ''}>
                <title>{section['name']}</title>
                {section_items}
            </item>"""
    
    # Add standalone activities that don't belong to any section
    for activity in standalone_activities:
        if activity['id'] not in [s['info']['id'] for s in sections.values()]:
            items_xml += f"""
            <item identifier="item_{activity['id']}" identifierref="resource_{activity['id']}">
                <title>{activity['name']}</title>
            </item>"""
    
    manifest_xml = f"""<?xml version="1.0" standalone="no" ?>
<manifest identifier="{org_identifier}" version="1"
         xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
         xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd
                             http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd
                             http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">

  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  
  <organizations default="{org_identifier}_org">
    <organization identifier="{org_identifier}_org">
      <title>{course_title}</title>
      {items_xml}
    </organization>
  </organizations>
  
  <resources>
    {resources_xml}
  </resources>
</manifest>
"""
    
    return manifest_xml

def create_scorm_package(activities, course_info, base_url):
    """Create a SCORM package with the extracted activities"""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a unique identifier for the organization
        org_identifier = f"scorm_package_{uuid.uuid4().hex[:8]}"
        
        # Create HTML files for each activity
        for activity in activities:
            html_content = create_html_page(activity['id'], activity['name'], base_url)
            with open(os.path.join(temp_dir, f"{activity['id']}.html"), 'w', encoding='utf-8') as f:
                f.write(html_content)
        
        # Create imsmanifest.xml
        manifest_content = create_imsmanifest(course_info['title'], activities, org_identifier)
        with open(os.path.join(temp_dir, "imsmanifest.xml"), 'w', encoding='utf-8') as f:
            f.write(manifest_content)
        
        # Copy your existing XSD files (assuming they are in the current directory)
        xsd_files = ["adlcp_rootv1p2.xsd", "ims_xml.xsd", "imscp_rootv1p1p2.xsd", "imsmd_rootv1p2p1.xsd"]
        for xsd_file in xsd_files:
            # Assuming the XSD files are in the same directory as the script
            if os.path.exists(xsd_file):
                shutil.copy(xsd_file, os.path.join(temp_dir, xsd_file))
            else:
                st.warning(f"Schema file {xsd_file} not found. The SCORM package may not work correctly.")
        
        # Create a ZIP file
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zf.write(file_path, arcname)
        
        memory_file.seek(0)
        return memory_file

if uploaded_file is not None and base_url:
    # Process the uploaded file
    try:
        xml_content = uploaded_file.read().decode('utf-8')
        
        # Extract activities and course info
        activities = extract_activities(xml_content)
        course_info = get_course_info(xml_content)
        
        # Display extracted information
        st.subheader("Extracted Course Information")
        st.write(f"Title: {course_info['title']}")
        st.write(f"Total activities: {len(activities)}")
        
        # Create dataframe for displaying activities
        import pandas as pd
        activities_df = pd.DataFrame(activities)
        activities_df = activities_df.rename(columns={
            'id': 'ID', 
            'name': 'Name', 
            'type': 'Type'
        })
        
        st.subheader("Activities to be Included")
        st.dataframe(activities_df[['ID', 'Name', 'Type']])
        
        # Create SCORM package button
        if st.button("Generate SCORM Package"):
            with st.spinner("Generating SCORM package..."):
                zipfile_bytes = create_scorm_package(activities, course_info, base_url)
                
                # Create download button
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"scorm_package_{timestamp}.zip"
                
                st.success("SCORM package generated successfully!")
                
                # Provide download link
                b64 = base64.b64encode(zipfile_bytes.getvalue()).decode()
                href = f'<a href="data:application/zip;base64,{b64}" download="{filename}">Download SCORM Package</a>'
                st.markdown(href, unsafe_allow_html=True)
                
                # Show instructions
                st.subheader("Next Steps")
                st.write("""
                1. Download the SCORM package using the link above.
                2. Import the package into your Learning Management System (LMS).
                3. Test the package to ensure it works correctly.
                """)
    except Exception as e:
        st.error(f"Error processing the file: {str(e)}")
else:
    # Show instructions
    st.info("""
    ## Instructions
    
    1. Upload your Rise TinCan XML file.
    2. Enter the base URL of your Rise content (the URL where your content is hosted without the /index.html part).
    3. Click "Generate SCORM Package" to create a SCORM 1.2 package.
    4. Download the ZIP file and import it into your LMS.
    
    ## What this app does
    
    This app takes your Rise TinCan XML file and creates separate HTML pages for each activity marked as 'blocks' or 'sections'.
    Each HTML page contains an iframe that loads the specific lesson from your Rise content.
    The app generates all the necessary SCORM 1.2 files and packages everything into a ZIP file that can be imported into most Learning Management Systems.
    """)
    
    st.subheader("Example")
    st.write("""
    If your Rise content is hosted at `https://example.com/rise-content/` and you have a lesson with ID `abc123`,
    the app will create an HTML page with an iframe pointing to `https://example.com/rise-content/index.html#/lessons/abc123`.
    """)
