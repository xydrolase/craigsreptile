<?php
$address = $_REQUEST['address'];
$sensor = $_REQUEST['sensor'];

$url = 'http://maps.googleapis.com/maps/api/geocode/json?address='.
    urlencode($address).'&sensor='.$sensor;

$result = http_get($url, false, null);
if ($result['code'] != 200){
    header('HTTP/1.1 400 Bad Request');
}

die($result['content']);

function http_get($url, $header = false, $cookie = null){
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false);	// do not follow the 302 See Other header
    curl_setopt($ch, CURLOPT_HEADER, $header);

    if ($cookie){
        if (is_array($cookie)){
            $cookie = implode(' ', $cookie);
        }
        curl_setopt($ch, CURLOPT_COOKIE, $cookie);
    }

    $content = curl_exec($ch);
    $http_code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    $headers = null;
    if ($header){
        // split the header information
        $pos = strpos($content, "\n\n");
        if ($pos !== false){
            $headers = substr($content, 0, $pos);
            $content = substr($content, $pos);
        }
    }

    return array('code'=> $http_code, 'content' => $content, 'header' => $headers);
}
?>
