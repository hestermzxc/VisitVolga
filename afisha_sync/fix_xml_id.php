<?php
// Проставляет внешний код (XML_ID) = ID для элементов афиши, у которых он отличается.
// Нужно потому, что копии событий наследуют XML_ID оригинала, а импорт CSV ищет элементы по XML_ID.
// Запуск: админка → Настройки → Инструменты → Командная PHP-строка. Вставить код без строки "<?php".
// 1) Запустить с $dryRun = true — скрипт только выведет список, ничего не меняя.
// 2) Проверить список, поставить $dryRun = false и запустить ещё раз.

$dryRun = true;
$sampleElementId = 4533; // любой элемент афиши (Спектакль «Тартюф») — по нему определяется инфоблок

\Bitrix\Main\Loader::includeModule('iblock');
$iblockId = (int)CIBlockElement::GetIBlockByID($sampleElementId);
if (!$iblockId) { echo "Инфоблок не найден"; return; }

$el = new CIBlockElement;
$res = CIBlockElement::GetList(['ID' => 'ASC'], ['IBLOCK_ID' => $iblockId], false, false, ['ID', 'XML_ID', 'NAME']);
$n = 0;
while ($r = $res->Fetch()) {
    if ((string)$r['XML_ID'] === (string)$r['ID']) continue;
    $n++;
    echo $r['ID'] . ': "' . $r['XML_ID'] . '" -> "' . $r['ID'] . '"  ' . $r['NAME'] . "\n";
    if (!$dryRun && !$el->Update($r['ID'], ['XML_ID' => $r['ID']])) {
        echo "  ОШИБКА: " . $el->LAST_ERROR . "\n";
    }
}
echo "\nИнфоблок $iblockId, элементов с XML_ID != ID: $n" . ($dryRun ? " (пробный запуск, ничего не изменено)" : " — исправлено");
